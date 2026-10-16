"""Transcription server: loads one STT model once, serves it over HTTP.

Entrypoint -- run directly via start.bat/start_hidden.bat
(see README.md for configuration). Keeps the model resident in VRAM
between requests. Which engine runs is picked by KUBUNDICTATE_MODEL at
startup (see backends/); switch_model.ps1 changes it and restarts.
"""

import os
import time

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import backends
from audio import wav_bytes_to_float32

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
MODEL = os.environ.get("KUBUNDICTATE_MODEL", "large-v3-turbo")
LANGUAGE = os.environ.get("KUBUNDICTATE_LANGUAGE") or None  # None = auto-detect
HOST = os.environ.get("KUBUNDICTATE_HOST", "0.0.0.0")
PORT = int(os.environ.get("KUBUNDICTATE_PORT", "9505"))
TOKEN = os.environ.get("KUBUNDICTATE_TOKEN") or None

# --------------------------------------------------------------------------

app = FastAPI()
_backend: backends.Backend | None = None
_bearer = HTTPBearer(auto_error=False)


def _check_auth(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    if TOKEN is None:
        return
    if credentials is None or credentials.credentials != TOKEN:
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "backend": _backend.name if _backend else None}


@app.post("/transcribe")
async def transcribe(audio: UploadFile, _auth=Depends(_check_auth)):
    wav_bytes = await audio.read()
    samples = wav_bytes_to_float32(wav_bytes)

    print(f"[transcribing {len(samples) / 16000:.1f}s of audio...]")
    t0 = time.time()
    text = _backend.transcribe(samples, LANGUAGE)
    elapsed = time.time() - t0
    print(f'[{elapsed:.2f}s] "{text}"')

    return {"text": text, "elapsed": elapsed}


def _lan_ip() -> str | None:
    # UDP "connect" doesn't send packets; it just makes the OS pick the
    # outbound-facing local IP via the routing table.
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _tailscale_ip() -> str | None:
    import subprocess

    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=2
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def main():
    global _backend
    _backend = backends.load(MODEL)
    print(f"Model loaded. Serving on http://{HOST}:{PORT} (token auth: {'on' if TOKEN else 'off'})")

    lan_ip = _lan_ip()
    if lan_ip:
        print(f"This is your Server IP: {lan_ip}")
    tailscale_ip = _tailscale_ip()
    if tailscale_ip:
        print(f"This is your Tailscale IP: {tailscale_ip}")

    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
