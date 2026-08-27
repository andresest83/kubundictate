"""Push-to-talk record/transcribe engine, used by tray_client.py.

Hold the hotkey, speak, release it, and the transcription lands on the
clipboard ready to paste (Ctrl+V). Not a standalone entrypoint --
imported by tray_client.py, which owns the stop_event passed to run().
"""

import os
import queue
import sys
import time

import numpy as np
import requests
import sounddevice as sd
import pyperclip
from pynput import keyboard

from audio import float32_to_wav_bytes

# Diagnostics sink. The tray clients replace this with their file logger:
# they run under pythonw.exe (Windows) or detached (Mac), where there is
# no console and a bare print() goes nowhere.
log = print

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
class Settings:
    """Mutable so a caller (e.g. tray_client.py) can switch servers live."""

    server_url = os.environ.get("KUBUNDICTATE_SERVER_URL")
    token = os.environ.get("KUBUNDICTATE_TOKEN") or None


settings = Settings()
SAMPLE_RATE = 16000
# Bare F-keys on a Mac keyboard default to hardware/media functions (need
# fn held to send the real F9 keycode) -- Left Option is a single,
# unmodified key that doesn't collide with anything, so it's the mac
# default instead. Windows keeps F9, untouched.
if sys.platform == "darwin":
    HOTKEY = keyboard.Key.alt_l
    HOTKEY_NAME = "Left Option"
else:
    HOTKEY = keyboard.Key.f9
    HOTKEY_NAME = "F9"
REQUEST_TIMEOUT = 120  # seconds

# Audio-stream supervision (see _supervise_audio). The input callback
# fires continuously once the stream is running -- whether or not we are
# recording -- so its timestamp doubles as a liveness heartbeat.
AUDIO_POLL_SECONDS = 2
AUDIO_RETRY_SECONDS = 3
AUDIO_SILENCE_TIMEOUT = 5  # no callback for this long means the stream is dead

# --------------------------------------------------------------------------

_recording = False
_transcribing = False
_frames = []
_audio_queue = queue.Queue()

# Set once per finished transcription attempt (success, no-speech, or
# request error) -- (text_or_None, error_or_None, sequence_number).
# GUI clients already poll is_recording()/is_transcribing() on a timer for
# icon state (#8); this is the same pattern, not a callback, so it stays
# free of any GUI-thread-affinity assumptions. The sequence number lets a
# poller detect a *new* result even when text/error repeats.
last_result = None
_result_seq = 0


def _set_result(text, error):
    global last_result, _result_seq
    _result_seq += 1
    last_result = (text, error, _result_seq)


_last_audio_at = 0.0  # monotonic time of the most recent input callback
_callback_count = 0


def _on_audio(indata, frames_count, time_info, status):
    global _last_audio_at, _callback_count
    _last_audio_at = time.monotonic()
    _callback_count += 1
    if status:
        # Overflows/underflows from PortAudio. Rare, and only worth a line
        # when they actually happen.
        log(f"audio callback status: {status}")
    if _recording:
        _audio_queue.put(indata.copy())


def _beep(freq, duration_ms):
    try:
        import winsound

        winsound.Beep(freq, duration_ms)
        return
    except Exception:
        pass  # not on Windows, or winsound failed (e.g. no default audio
        # device) -- fall through to the sounddevice tone below either way

    try:
        t = np.linspace(0, duration_ms / 1000, int(SAMPLE_RATE * duration_ms / 1000), endpoint=False)
        tone = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
        sd.play(tone, SAMPLE_RATE)
        sd.wait()
    except Exception:
        pass


def _drain_queue_into(frames_list):
    while True:
        try:
            frames_list.append(_audio_queue.get_nowait())
        except queue.Empty:
            break


def is_recording():
    return _recording


def is_transcribing():
    return _transcribing


def start_recording():
    global _recording, _frames
    _frames = []
    with _audio_queue.mutex:
        _audio_queue.queue.clear()
    _recording = True
    _beep(880, 80)
    log(f"hotkey down -- recording (callbacks so far: {_callback_count})")


def stop_recording_and_transcribe():
    global _recording, _transcribing
    _recording = False
    _drain_queue_into(_frames)
    _beep(440, 80)
    log(f"hotkey up -- captured {len(_frames)} audio blocks")

    if not _frames:
        # Nothing arrived at all: the stream is not delivering. Distinct
        # from capturing silence, which still produces blocks -- see the
        # peak level logged below.
        log("no audio captured -- the input stream delivered nothing")
        _set_result(None, "aborted")
        return

    audio = np.concatenate(_frames, axis=0).flatten().astype(np.float32)
    duration = len(audio) / SAMPLE_RATE
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    log(f"captured {duration:.2f}s, peak level {peak:.4f}")
    if peak < 1e-6:
        # Blocks arrived but every sample is zero. On macOS that is what
        # a denied microphone permission looks like: the stream opens and
        # runs, it just never carries any sound.
        log(
            "WARNING: audio is pure silence. On macOS check System Settings"
            " -> Privacy & Security -> Microphone; on Windows check the input"
            " device is not muted."
        )
    if duration < 0.2:
        log("clip too short, ignored")
        _set_result(None, "aborted")
        return

    log(f"sending {duration:.2f}s to {settings.server_url}")
    wav_bytes = float32_to_wav_bytes(audio, SAMPLE_RATE)
    headers = {"Authorization": f"Bearer {settings.token}"} if settings.token else {}

    _transcribing = True
    started = time.monotonic()
    try:
        try:
            resp = requests.post(
                f"{settings.server_url}/transcribe",
                files={"audio": ("clip.wav", wav_bytes, "audio/wav")},
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            log(f"server replied {resp.status_code} in {time.monotonic() - started:.1f}s")
            resp.raise_for_status()
            text = resp.json()["text"]
        except requests.RequestException as e:
            log(f"could not reach server: {e}")
            _beep(220, 200)
            _set_result(None, "could not reach server")
            return
        except (ValueError, KeyError) as e:
            # Reached the server but the body was not the JSON we expect.
            log(f"unexpected reply from server: {e}; body was {resp.text[:200]!r}")
            _beep(220, 200)
            _set_result(None, "could not reach server")
            return

        if text:
            pyperclip.copy(text)
            log(f"transcribed {len(text)} chars, copied to clipboard")
            _beep(1200, 60)
            _set_result(text, None)
        else:
            log("server returned no text (no speech detected)")
            _set_result(None, "no speech detected")
    finally:
        _transcribing = False


def run(stop_event):
    """Runs the record/transcribe hotkey loop until stop_event is set.

    Owned by tray_client.py, which runs this in a background thread and
    sets stop_event from its Quit menu item to stop it cleanly.
    """
    if not settings.server_url:
        raise SystemExit(
            "KUBUNDICTATE_SERVER_URL is not set. Point it at the server, "
            "e.g. http://192.168.1.50:9505"
        )

    log(f"Server: {settings.server_url} (token auth: {'on' if settings.token else 'off'})")
    log(f"Hold {HOTKEY_NAME} to talk, release to transcribe + copy to clipboard.")

    def on_press(key):
        if key == HOTKEY and not _recording:
            start_recording()

    def on_release(key):
        if key == HOTKEY and _recording:
            stop_recording_and_transcribe()

    def start_listener():
        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.start()
        return listener

    listener = start_listener()
    try:
        _supervise_audio(stop_event, listener, start_listener)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            listener.stop()
        except Exception:
            pass
        log("Goodbye.")


def _open_stream():
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=_on_audio,
    )
    stream.start()
    return stream


def _close_stream(stream):
    if stream is None:
        return
    try:
        stream.stop()
        stream.close()
    except Exception:
        pass


def _supervise_audio(stop_event, listener, start_listener):
    """Keeps a working input stream (and hotkey listener) alive.

    The stream used to be opened once at startup and never looked at
    again, which broke in two ways, both seen on the GPU box:

    - Opening it before Windows has a default input device -- right after
      boot, or with no mic attached -- raised straight out of this
      thread. That killed recording for the entire session, silently: the
      tray icon and hotkey carried on as if nothing were wrong.
    - A sleep/resume cycle can leave PortAudio holding a handle that
      still reports itself open but never delivers another callback.
      Same outcome, and the only cure was quitting and relaunching.

    So the stream is opened with retries rather than once, and then
    watched. _on_audio fires continuously while the stream is healthy --
    recording or not -- so a stale timestamp is a reliable "this is dead"
    signal, more so than stream.active, which stays True in the
    resume-from-sleep case.

    The hotkey listener gets the same treatment: pynput's global hook can
    also be dropped across a resume, with the same invisible result.
    """
    global _last_audio_at
    stream = None
    listener_dead_checks = 0
    while not stop_event.is_set():
        if stream is None:
            try:
                _last_audio_at = time.monotonic()  # grace period before judging it
                stream = _open_stream()
            except Exception as exc:
                log(f"Audio input unavailable ({exc}); retrying in {AUDIO_RETRY_SECONDS}s")
                stop_event.wait(AUDIO_RETRY_SECONDS)
                continue
            # Naming the device is only for the log -- keep it out of the
            # block above so a failure here can't be mistaken for the
            # stream itself having failed to open.
            try:
                log(f"Audio input opened: {sd.query_devices(kind='input')['name']}")
            except Exception:
                log("Audio input opened")

        stop_event.wait(AUDIO_POLL_SECONDS)
        if stop_event.is_set():
            break

        try:
            silent_for = time.monotonic() - _last_audio_at
            dead = silent_for > AUDIO_SILENCE_TIMEOUT or not stream.active
            if dead:
                log(
                    f"Audio input stopped responding "
                    f"(active={stream.active}, no data for {silent_for:.0f}s) -- reopening"
                )
        except Exception as exc:
            log(f"Audio input check failed ({exc}) -- reopening")
            dead = True

        if dead:
            _close_stream(stream)
            stream = None

        # Deliberately cautious. Replacing the listener mid-keypress loses
        # the release event, which leaves a recording that never stops --
        # you get the start beep and then nothing at all. So: never while
        # the user is mid-dictation, and only after it has looked dead on
        # two consecutive checks, since pynput can report `running` False
        # transiently while starting up.
        if _recording or _transcribing:
            listener_dead_checks = 0
        elif listener.running:
            listener_dead_checks = 0
        else:
            listener_dead_checks += 1
            if listener_dead_checks >= 2:
                listener_dead_checks = 0
                log("Hotkey listener stopped -- restarting it")
                try:
                    listener.stop()
                except Exception:
                    pass
                try:
                    listener = start_listener()
                except Exception as exc:
                    log(f"Could not restart the hotkey listener ({exc})")

    _close_stream(stream)
