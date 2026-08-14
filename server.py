"""Transcription server: loads faster-whisper once, serves it over HTTP.

Run via `kubundictate.py` with KUBUNDICTATE_MODE=server (see README.md for
configuration). Keeps the model resident in VRAM between requests.
"""

import os
import time

# --- CUDA DLL setup (Windows needs these on PATH before ctranslate2 loads) ---
# The nvidia-cublas-cu12/nvidia-cudnn-cu12 pip packages ship their DLLs
# under <pkg>/bin on Windows (unlike the lib/ layout on Linux). ctranslate2
# resolves them via plain LoadLibrary, which only honors PATH -- adding
# them via os.add_dll_directory alone is not enough.
try:
    import nvidia.cublas
    import nvidia.cudnn

    _cublas_bin = os.path.join(list(nvidia.cublas.__path__)[0], "bin")
    _cudnn_bin = os.path.join(list(nvidia.cudnn.__path__)[0], "bin")
    os.environ["PATH"] = _cublas_bin + os.pathsep + _cudnn_bin + os.pathsep + os.environ["PATH"]
except ImportError:
    pass

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from faster_whisper import WhisperModel

from audio import wav_bytes_to_float32

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
MODEL_SIZE = os.environ.get("KUBUNDICTATE_MODEL", "large-v3-turbo")
DEVICE = "cuda"
# NOTE: default/int8 compute types trigger CUBLAS_STATUS_NOT_SUPPORTED on
# Blackwell (RTX 50-series) GPUs. float16 is the known-good workaround.
COMPUTE_TYPE = "float16"
LANGUAGE = os.environ.get("KUBUNDICTATE_LANGUAGE") or None  # None = auto-detect
HOST = os.environ.get("KUBUNDICTATE_HOST", "0.0.0.0")
PORT = int(os.environ.get("KUBUNDICTATE_PORT", "8000"))
TOKEN = os.environ.get("KUBUNDICTATE_TOKEN") or None

# --------------------------------------------------------------------------

app = FastAPI()
_model: WhisperModel | None = None
_bearer = HTTPBearer(auto_error=False)


def _check_auth(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    if TOKEN is None:
        return
    if credentials is None or credentials.credentials != TOKEN:
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_SIZE}


@app.post("/transcribe")
async def transcribe(audio: UploadFile, _auth=Depends(_check_auth)):
    wav_bytes = await audio.read()
    samples = wav_bytes_to_float32(wav_bytes)

    print(f"[transcribing {len(samples) / 16000:.1f}s of audio...]")
    t0 = time.time()
    segments, _info = _model.transcribe(
        samples,
        language=LANGUAGE,
        vad_filter=True,
        beam_size=5,
    )
    text = "".join(seg.text for seg in segments).strip()
    elapsed = time.time() - t0
    print(f'[{elapsed:.2f}s] "{text}"')

    return {"text": text, "elapsed": elapsed}


def main():
    global _model
    print(f"Loading model '{MODEL_SIZE}' on {DEVICE} ({COMPUTE_TYPE})...")
    _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    print(f"Model loaded. Serving on http://{HOST}:{PORT} (token auth: {'on' if TOKEN else 'off'})")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
