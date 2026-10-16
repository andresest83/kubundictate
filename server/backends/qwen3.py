"""Alibaba Qwen3-ASR-1.7B via the qwen-asr package (transformers backend).

Supports 30 languages; English, Spanish, Italian and German are among
them. With no language hint it detects the language itself.
"""

import torch
from qwen_asr import Qwen3ASRModel

from . import Backend

SAMPLE_RATE = 16000

# KUBUNDICTATE_LANGUAGE is an ISO code; qwen-asr wants the English name.
# Only the languages we've been asked to support are mapped -- anything
# else falls back to auto-detect rather than guessing a spelling.
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "it": "Italian",
    "de": "German",
}


class Qwen3Backend(Backend):
    def __init__(self, model_id: str):
        self.name = f"qwen3-asr:{model_id}"
        print(f"Loading model '{model_id}' on CUDA (bfloat16)...")
        self._model = Qwen3ASRModel.from_pretrained(
            model_id,
            dtype=torch.bfloat16,
            device_map="cuda:0",
            # One clip at a time; no point reserving memory for batches.
            max_inference_batch_size=1,
            max_new_tokens=512,
        )

    def transcribe(self, samples, language):
        results = self._model.transcribe(
            audio=(samples, SAMPLE_RATE),
            language=LANGUAGE_NAMES.get((language or "").lower()),
        )
        return results[0].text.strip()

    def close(self):
        del self._model
        torch.cuda.empty_cache()


def load(model_id: str) -> Backend:
    return Qwen3Backend(model_id)
