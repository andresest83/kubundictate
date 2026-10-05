"""Inworld cloud speech-to-text, the client's alternative to our own server.

Used by client.py when the active server-list entry has
"provider": "inworld" (#47). Same WAV that goes to server.py goes here
instead -- 16 kHz mono 16-bit PCM is exactly what Inworld's sync endpoint
recommends, so there is no extra audio handling, only a different
envelope: JSON with the audio base64-encoded, rather than a multipart
upload.

The API key comes from the entry's "api_key" if set, otherwise from the
INWORLD_API_KEY environment variable. It is sent as-is after "Basic "
(Inworld issues it already base64-encoded) and is never logged.
"""

import base64
import os

import requests

URL = "https://api.inworld.ai/stt/v1/transcribe"
MODEL_ID = "inworld/inworld-stt-1"
KEY_ENV_VAR = "INWORLD_API_KEY"


class KeyProblem(Exception):
    """No API key available, or Inworld rejected the one we sent."""


def resolve_key(api_key):
    """Returns (key, source) -- source is for log lines, never the key."""
    if api_key:
        return api_key, "settings file"
    key = os.environ.get(KEY_ENV_VAR)
    if key:
        return key, f"{KEY_ENV_VAR} env var"
    return None, None


def transcribe(wav_bytes, api_key, language, timeout):
    """Sends one clip to Inworld and returns the transcript text.

    Raises KeyProblem for a missing or rejected key, and lets
    requests.RequestException through for everything else (network
    failure, other HTTP errors) so the caller treats it like an
    unreachable server.
    """
    key, _source = resolve_key(api_key)
    if not key:
        raise KeyProblem(f"no API key: set {KEY_ENV_VAR} or the entry's api_key")

    config = {"modelId": MODEL_ID, "audioEncoding": "LINEAR16"}
    # Omitted rather than sent empty: no hint means auto-detect, which
    # also lets the spoken language change from one clip to the next.
    if language:
        config["language"] = language

    resp = requests.post(
        URL,
        json={
            "transcribeConfig": config,
            "audioData": {"content": base64.b64encode(wav_bytes).decode("ascii")},
        },
        headers={"Authorization": f"Basic {key}"},
        timeout=timeout,
    )
    if resp.status_code in (401, 403):
        raise KeyProblem(f"key rejected (HTTP {resp.status_code}): {resp.text[:200]}")
    if not resp.ok:
        # Inworld's error body (gRPC-style code + message) is the useful
        # part for the log; raise_for_status alone would drop it.
        raise requests.HTTPError(
            f"HTTP {resp.status_code}: {resp.text[:300]}", response=resp
        )
    return resp.json().get("transcription", {}).get("transcript", "").strip()
