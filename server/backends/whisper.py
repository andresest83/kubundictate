"""faster-whisper backend -- the original engine, behavior unchanged."""

from . import Backend, cuda_dlls

cuda_dlls.add_to_path()

from faster_whisper import WhisperModel  # noqa: E402  (needs the PATH set above)

DEVICE = "cuda"
# NOTE: default/int8 compute types trigger CUBLAS_STATUS_NOT_SUPPORTED on
# Blackwell (RTX 50-series) GPUs. float16 is the known-good workaround.
COMPUTE_TYPE = "float16"


class WhisperBackend(Backend):
    def __init__(self, model_size: str):
        self.name = f"whisper:{model_size}"
        print(f"Loading model '{model_size}' on {DEVICE} ({COMPUTE_TYPE})...")
        self._model = WhisperModel(model_size, device=DEVICE, compute_type=COMPUTE_TYPE)

    def transcribe(self, samples, language):
        segments, _info = self._model.transcribe(
            samples,
            language=language,
            vad_filter=True,
            beam_size=5,
            # Without this, each segment's decoding is seeded with the
            # previous segment's *text*. On a low-confidence/silent tail
            # that snowballs -- one hallucinated "Bye bye." makes the next
            # segment more likely to repeat it, and so on (#30).
            condition_on_previous_text=False,
        )
        # Drop segments faster-whisper itself flags as low-confidence/silent
        # or repetitive, instead of appending every segment as-is. Same
        # thresholds as Whisper's own reference decoder.
        return "".join(
            seg.text
            for seg in segments
            if seg.no_speech_prob < 0.6
            and seg.avg_logprob > -1.0
            and seg.compression_ratio < 2.4
        ).strip()

    def close(self):
        del self._model


def load(model_size: str) -> Backend:
    return WhisperBackend(model_size)
