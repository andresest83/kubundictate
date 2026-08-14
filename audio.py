"""WAV <-> float32 PCM conversion shared by the client and server.

Recorded audio is captured as float32 (via sounddevice) on the client but
travels over HTTP as WAV/PCM16 bytes, then gets converted back to float32
on the server for faster-whisper. Uses only the stdlib `wave` module --
no extra dependency needed on either side.
"""

import io
import wave

import numpy as np


def float32_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    pcm16 = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm16 * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def wav_bytes_to_float32(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data), "rb") as wf:
        pcm16 = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return (pcm16.astype(np.float32) / 32767.0)
