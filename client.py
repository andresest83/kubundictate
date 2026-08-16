"""Push-to-talk client: records locally, transcribes via a remote server.

Hold the hotkey, speak, release it, and the transcription (fetched from
KUBUNDICTATE_SERVER_URL) lands on the clipboard ready to paste (Ctrl+V).
Run via `kubundictate.py` with KUBUNDICTATE_MODE=client (see README.md).
"""

import os
import queue
import threading

import numpy as np
import requests
import sounddevice as sd
import pyperclip
from pynput import keyboard

from audio import float32_to_wav_bytes

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
class Settings:
    """Mutable so a caller (e.g. tray_client.py) can switch servers live."""

    server_url = os.environ.get("KUBUNDICTATE_SERVER_URL")
    token = os.environ.get("KUBUNDICTATE_TOKEN") or None


settings = Settings()
SAMPLE_RATE = 16000
HOTKEY = keyboard.Key.f9  # hold to record, release to transcribe
REQUEST_TIMEOUT = 120  # seconds

# --------------------------------------------------------------------------

_recording = False
_frames = []
_audio_queue = queue.Queue()


def _on_audio(indata, frames_count, time_info, status):
    if _recording:
        _audio_queue.put(indata.copy())


def _beep(freq, duration_ms):
    try:
        import winsound

        winsound.Beep(freq, duration_ms)
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


def start_recording():
    global _recording, _frames
    _frames = []
    with _audio_queue.mutex:
        _audio_queue.queue.clear()
    _recording = True
    _beep(880, 80)
    print("[recording...]")


def stop_recording_and_transcribe():
    global _recording
    _recording = False
    _drain_queue_into(_frames)
    _beep(440, 80)

    if not _frames:
        print("[no audio captured]")
        return

    audio = np.concatenate(_frames, axis=0).flatten().astype(np.float32)
    duration = len(audio) / SAMPLE_RATE
    if duration < 0.2:
        print("[clip too short, ignored]")
        return

    print(f"[sending {duration:.1f}s of audio to {settings.server_url}...]")
    wav_bytes = float32_to_wav_bytes(audio, SAMPLE_RATE)
    headers = {"Authorization": f"Bearer {settings.token}"} if settings.token else {}

    try:
        resp = requests.post(
            f"{settings.server_url}/transcribe",
            files={"audio": ("clip.wav", wav_bytes, "audio/wav")},
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.json()["text"]
    except requests.RequestException as e:
        print(f"[error: could not reach server: {e}]")
        _beep(220, 200)
        return

    if text:
        pyperclip.copy(text)
        print(f'"{text}"  (copied to clipboard)')
        _beep(1200, 60)
    else:
        print("[no speech detected]")


def run(stop_event, quit_on_esc=True):
    """Runs the record/transcribe hotkey loop until stop_event is set.

    Shared by the plain console client (main(), below) and the tray
    client, which owns stop_event itself so its Quit menu item can stop
    this cleanly from another thread.
    """
    if not settings.server_url:
        raise SystemExit(
            "KUBUNDICTATE_SERVER_URL is not set. Point it at the server, "
            "e.g. http://192.168.1.50:50505"
        )

    print(f"Server: {settings.server_url} (token auth: {'on' if settings.token else 'off'})")
    print("Hold F9 to talk, release to transcribe + copy to clipboard.")
    if quit_on_esc:
        print("Press Esc (while not recording) to quit.")

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=_on_audio,
    )
    stream.start()

    def on_press(key):
        if key == HOTKEY and not _recording:
            start_recording()

    def on_release(key):
        if key == HOTKEY and _recording:
            stop_recording_and_transcribe()
        elif quit_on_esc and key == keyboard.Key.esc and not _recording:
            stop_event.set()
            return False

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        stream.stop()
        stream.close()
        print("Goodbye.")


def main():
    run(threading.Event())


if __name__ == "__main__":
    main()
