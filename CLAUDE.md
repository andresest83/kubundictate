# KubunDictate

Local, offline push-to-talk dictation via faster-whisper. See
[README.md](README.md) for what it does, setup, and configuration --
this file covers Claude-specific working agreement and roadmap only.

## Working agreement

- Claude acts as engineering manager on this project; the user is the PM.
  Claude drives technical decisions but stays aligned with the user's
  direction rather than running ahead unilaterally.
- No installs performed by Claude -- the user installs tools/dependencies
  (e.g. Git, GitHub CLI) themselves.
- No direct pushes to `main` -- all work happens on feature branches with
  PRs, from the first commit onward.
- No large/architectural changes without planning with the user first --
  don't jump straight to installs or big modifications unilaterally.

## Roadmap: LAN-accessible dictation

Goal: reach KubunDictate from any device on the LAN -- and from off-LAN
via Tailscale -- starting with Windows.

Status:

1. **Windows** -- done. `server.py` (FastAPI + Uvicorn, GPU box) and
   `client.py` (hotkey/record/clipboard, any Windows PC) split out of the
   original single-file script, wired together via `kubundictate.py` and
   `KUBUNDICTATE_MODE`. See README.md for details.
2. **Mac client** -- next. A `client.py`-equivalent for macOS: same
   HTTP contract against `server.py`, different hotkey/audio-capture
   libraries where `pynput`/`sounddevice` don't behave the same on macOS.
   Not yet scoped in detail -- plan before coding.
3. **Android client** -- later; not yet scoped.

Architecture that's now in place and should be preserved by future
clients (Mac, Android):

- **Server**: FastAPI + Uvicorn on the GPU box, model loaded once and
  resident, exposes `POST /transcribe` (multipart WAV upload -> JSON
  `{text, elapsed}`) and `GET /health`.
- **Auth**: optional shared bearer token (`KUBUNDICTATE_TOKEN`), off by
  default.
- **Remote access**: LAN, plus Tailscale for off-LAN use. No other WAN
  exposure.
- **Hosting**: public, open-source GitHub repo (`andresest83/kubundictate`)
  so other devices can clone it. Feature branches + PRs only.

## Product notes (from FluidVoice review, 2026-08-14)

Reviewed [FluidVoice](https://github.com) (macOS native dictation app) as
a competitive reference point. Findings that should shape KubunDictate's
direction:

- **The LAN client/server split is the real differentiator**, not text
  formatting. FluidVoice is a single-machine macOS app; its internal
  HTTP API is hard-locked to loopback only (rejects any non-127.0.0.1
  connection), so it has no equivalent to one shared GPU serving several
  thin clients. Lead with this in any portfolio/positioning framing.
- **Open design question: auto-paste vs. clipboard-only.** Currently the
  client copies text to the clipboard and the user pastes manually
  (Ctrl+V). FluidVoice auto-types into the focused control, but its
  `TypingService.swift` needed five fallback strategies (~1350 lines) to
  handle inconsistent app behavior on macOS (Accessibility API quirks,
  per-app special-casing for Xcode/Notes/terminals). A Windows
  equivalent would likely be much smaller -- clipboard write + a
  synthetic Ctrl+V via `SendInput` -- but it's still simulating a
  keystroke into whatever window has focus, with real edge cases (user
  switches windows mid-transcription, target app rejects synthetic
  input). Not decided; needs a deliberate look before building, not a
  quick bolt-on.
- **Text formatting maturity arc.** FluidVoice's polished AI cleanup
  ("Fluid Intelligence") is actually closed-source -- the public repo's
  version is a stub that echoes text unchanged. What's genuinely open
  and reusable there is (a) a deterministic spoken-punctuation formatter
  and (b) a generic "send transcript + a user-configurable system prompt
  to any OpenAI-compatible endpoint" pipeline. That second one is the
  realistic next step for KubunDictate, and a better fit for where the
  user is headed (transitioning into AIOps/MLOps) than jumping straight
  to training a model: it's an actual inference-pipeline integration
  (provider routing, prompt config, API key handling) rather than a
  data/training project with much higher upfront cost and uncertain
  payoff. Sensible maturity arc: raw transcript (today) -> optional LLM
  cleanup pass (configurable local/cloud endpoint, next) -> maybe a
  fine-tuned/local model later, once real usage data shows what
  "cleanup" should actually look like. Iterating from simple to
  ML-heavy based on evidence is a stronger portfolio story than starting
  with training.
- **Process hygiene worth adopting**, independent of the ASR/formatting
  question: FluidVoice gates CI on a lint pass before the build even
  starts, uses a PR template with a testing checklist, has issue
  templates, a CONTRIBUTING.md, and skips CI on docs-only PRs via a path
  filter. Python/GitHub equivalents (ruff/black lint gate in a GitHub
  Actions workflow, PR template, issue templates, CONTRIBUTING.md) are
  cheap to add and read well for a portfolio repo.

To be turned into GitHub issues on `andresest83/kubundictate` later (not
yet done -- ask before creating).

## Files

See [README.md](README.md#files).
