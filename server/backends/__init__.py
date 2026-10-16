"""Speech-to-text backends: one module per engine, one resident at a time.

server.py asks `load(name)` for a backend once at startup and calls
`transcribe(samples)` per request, so it never imports an engine itself.
Engine modules are imported lazily, inside `load`, so a box running Whisper
doesn't need torch (or any other engine's dependencies) installed (#49).

KUBUNDICTATE_MODEL picks the backend. The aliases below name the
non-Whisper engines; any other value is treated as a faster-whisper model
name, which keeps every pre-#49 config.bat working unchanged.
"""

import numpy as np

# alias -> (backend module, model id passed to it)
ALIASES = {
    "parakeet-v3": ("parakeet", "nemo-parakeet-tdt-0.6b-v3"),
    "qwen3-asr-1.7b": ("qwen3", "Qwen/Qwen3-ASR-1.7B"),
}


class Backend:
    """What server.py needs from an engine."""

    name = ""  # shown by /health and in the log

    def transcribe(self, samples: np.ndarray, language: str | None) -> str:
        """16 kHz mono float32 in [-1, 1] -> text. `language` is an ISO
        code ("en", "de", ...) or None for auto-detect; engines that always
        auto-detect ignore it."""
        raise NotImplementedError

    def close(self) -> None:
        """Release GPU memory. Optional: the server exits to switch models,
        so this only matters to anything that loads two in one process."""


def load(model: str) -> Backend:
    module_name, model_id = ALIASES.get(model.lower(), ("whisper", model))
    if module_name == "whisper":
        from . import whisper as module
    elif module_name == "parakeet":
        from . import parakeet as module
    else:
        from . import qwen3 as module
    return module.load(model_id)
