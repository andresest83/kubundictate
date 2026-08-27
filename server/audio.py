"""WAV -> float32 PCM conversion, the server's half of the wire format.

Recorded audio is captured as float32 (via sounddevice) on the client but
travels over HTTP as WAV/PCM16 bytes, then gets converted back to float32
here for faster-whisper. Uses only the stdlib `wave` module -- no extra
dependency needed.

The encoding half lives in client/audio.py. The two are inverses: change
the format on one side and the other has to match.
"""

import io
import wave

import numpy as np


def wav_bytes_to_float32(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data), "rb") as wf:
        pcm16 = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return (pcm16.astype(np.float32) / 32767.0)
