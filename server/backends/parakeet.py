"""NVIDIA Parakeet TDT 0.6B v3 via onnx-asr (ONNX Runtime, CUDA).

Chosen over NeMo for Windows: onnx-asr needs only onnxruntime-gpu, not
NeMo's large dependency tree. The model auto-detects among its 25 European
languages (English, Spanish, Italian and German included), so `language`
is ignored.
"""

from pathlib import Path

import numpy as np

from . import Backend, cuda_dlls

cuda_dlls.add_to_path()

import onnx_asr  # noqa: E402  (needs the PATH set above)

SAMPLE_RATE = 16000
REPO_ID = "istupakov/parakeet-tdt-0.6b-v3-onnx"
# Next to the code, not in the Hugging Face cache: the boot-time task runs
# as SYSTEM, so the cache would be in its profile, and (the real reason)
# the cache stores files as symlinks into blobs/. ONNX Runtime refuses
# external weight files (encoder-model.onnx.data) that resolve outside the
# model's own directory, so a cached snapshot fails to load. Real files in
# a plain directory pass the check.
MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "parakeet-tdt-0.6b-v3-onnx"
# onnx-asr documents ~20-30 s as the most this model takes in one pass.
# Dictation clips are normally far shorter; longer ones are cut into
# fixed pieces rather than failing. A cut can land mid-word, which is why
# this is a fallback and not the normal path.
MAX_CHUNK_S = 20


def _fetch_model() -> None:
    """Downloads the model into MODEL_DIR (a no-op once it's all there).
    Offline with a complete copy on disk is fine; offline without is not."""
    from huggingface_hub import snapshot_download

    try:
        print(f"Checking model files in {MODEL_DIR} (first run downloads ~2.5 GB)...")
        # int8 variants are never loaded (quantization=None), skip them.
        snapshot_download(REPO_ID, local_dir=MODEL_DIR, ignore_patterns=["*int8*"])
    except Exception as e:
        if not (MODEL_DIR / "encoder-model.onnx").exists():
            raise
        print(f"Could not reach Hugging Face ({e}); using the copy on disk.")


class ParakeetBackend(Backend):
    def __init__(self, model_id: str):
        self.name = f"parakeet:{model_id}"
        _fetch_model()
        print(f"Loading model '{model_id}' on CUDA (onnx-asr)...")
        self._model = onnx_asr.load_model(
            model_id,
            MODEL_DIR,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        self._require_cuda()
        self._warm_up()

    def _warm_up(self):
        """The first inference after load takes ~35 s on the RTX 5060 Ti
        (CUDA kernels for the Blackwell GPU get compiled on first use);
        every one after it takes ~50 ms. Pay that here, before the server
        starts listening, instead of on the first dictation -- where the
        client sat on "Transcribing..." and looked hung."""
        print("Warming up (one-time GPU kernel compile, ~40 s)...")
        noise = (0.05 * np.random.randn(3 * SAMPLE_RATE)).astype(np.float32)
        self._model.recognize(noise, sample_rate=SAMPLE_RATE)

    def _require_cuda(self):
        """onnxruntime logs a CUDA failure and then quietly runs on the CPU
        instead -- it did exactly that when its CUDA 13 build met our CUDA 12
        libraries. That would pass every test and just be slow, so refuse."""
        try:
            providers = self._model.asr._encoder.get_providers()
        except AttributeError:
            print("WARNING: couldn't inspect onnx-asr's session; not verifying it is on the GPU.")
            return
        if "CUDAExecutionProvider" not in providers:
            raise RuntimeError(
                "Parakeet loaded on the CPU, not the GPU (providers: "
                f"{providers}). See the onnxruntime CUDA errors above -- usually an "
                "onnxruntime-gpu build that doesn't match the installed CUDA libraries."
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
