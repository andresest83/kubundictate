"""NVIDIA Parakeet TDT 0.6B v3 via onnx-asr (ONNX Runtime, CUDA).

Chosen over NeMo for Windows: onnx-asr needs only onnxruntime-gpu, not
NeMo's large dependency tree. The model auto-detects among its 25 European
languages (English, Spanish, Italian and German included), so `language`
is ignored.
"""

import numpy as np

from . import Backend, cuda_dlls

cuda_dlls.add_to_path()

import onnx_asr  # noqa: E402  (needs the PATH set above)

SAMPLE_RATE = 16000
# onnx-asr documents ~20-30 s as the most this model takes in one pass.
# Dictation clips are normally far shorter; longer ones are cut into
# fixed pieces rather than failing. A cut can land mid-word, which is why
# this is a fallback and not the normal path.
MAX_CHUNK_S = 20


class ParakeetBackend(Backend):
    def __init__(self, model_id: str):
        self.name = f"parakeet:{model_id}"
        print(f"Loading model '{model_id}' on CUDA (onnx-asr)...")
        self._model = onnx_asr.load_model(
            model_id,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )

    def transcribe(self, samples, language):
        step = MAX_CHUNK_S * SAMPLE_RATE
        pieces = [samples[i : i + step] for i in range(0, len(samples), step)]
        texts = [self._model.recognize(p, sample_rate=SAMPLE_RATE) for p in pieces]
        return " ".join(t.strip() for t in texts if t.strip())

    def close(self):
        del self._model


def load(model_id: str) -> Backend:
    return ParakeetBackend(model_id)
