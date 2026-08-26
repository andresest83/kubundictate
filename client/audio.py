"""float32 PCM -> WAV conversion, the client's half of the wire format.

Recorded audio is captured as float32 (via sounddevice) here, then travels
over HTTP as WAV/PCM16 bytes and gets converted back to float32 on the
server for faster-whisper. Uses only the stdlib `wave` module -- no extra
dependency needed.

The decoding half lives in server/audio.py. The two are inverses: change
the format on one side and the other has to match.
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
