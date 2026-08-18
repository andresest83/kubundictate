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
- New work starts as a GitHub issue on `andresest83/kubundictate`; feature
  branches and PRs reference the issue they implement.

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

## Issue backlog

Filed as GitHub issues on `andresest83/kubundictate`, one feature branch
per issue:

- [#2](https://github.com/andresest83/kubundictate/issues/2) **Run the
  server as a Windows service** (`priority: high`) -- **implemented and
  verified 2026-08-14** via `install_service.ps1` (Windows Scheduled
  Task, not a real service -- see PR
  [#9](https://github.com/andresest83/kubundictate/pull/9)). User
  confirmed the task ran successfully after a full reboot with the
  server coming up unattended. PR #9 targets `feature/windows-client-server`
  (not yet merged); merge #9 into that branch, then that branch into
  `main` via PR #1, to close out.
- [#3](https://github.com/andresest83/kubundictate/issues/3) **Automate
  the Windows Firewall inbound rule** (`priority: high`) -- **folded
  into #4**, see below.
- [#4](https://github.com/andresest83/kubundictate/issues/4) **One-shot
  installer** (`priority: high`) -- `install.ps1`: asks "server or
  client?", then creates the venv, installs the right requirements
  file, writes `config.bat`. Server path also provisions the firewall
  rule (closes #3) and can register the startup service (`install_service.ps1`,
  #2). Client path asks for the server's address and checks
  reachability instead of hand-editing `config.bat` (closes #8 pieces
  1-2 -- server prints its LAN/Tailscale IP at every startup via
  `server.py`, installer surfaces the same at the end of server setup).
  Mechanically a PowerShell bootstrap script, not winget -- winget needs
  a compiled installer (e.g. Inno Setup) plus a release/manifest
  pipeline on top of this; deliberately deferred as a fast-follow once
  `install.ps1` is proven out, not built alongside it.
- [#8](https://github.com/andresest83/kubundictate/issues/8) **Guided
  remote-client setup: endpoint discovery + Windows tray app**
  (`priority: high`) -- **implemented and verified 2026-08-17** via
  `tray_client.py` (PR [#13](https://github.com/andresest83/kubundictate/pull/13)).
  Pieces 1-2 shipped earlier via #4. Piece 3 built as a lightweight
  3-entry recent-servers MRU (not full named-endpoint management --
  wasn't needed). Piece 4: `pystray` tray icon (color-coded while
  recording), settings in `%APPDATA%\KubunDictate\client_settings.json`
  (separate from the server's `config.bat`), plus a **Run at startup**
  toggle (Registry Run key) that wasn't in the original issue text but
  came up during testing. User verified end-to-end including a full
  reboot with the startup toggle on.
- [#15](https://github.com/andresest83/kubundictate/issues/15)
  **Streamline server/client install and running** (`priority: high`)
  -- **implemented and verified 2026-08-18** via PR
  [#19](https://github.com/andresest83/kubundictate/pull/19).
  `start_local_client.bat` retired (the tray client points itself at
  `localhost` instead, pre-seeded by `install.ps1`), new `status.ps1`
  (one command, no elevation, task state + `/health`), `start_tray.bat`
  now detaches instead of blocking the calling terminal. Three real
  bugs found through hands-on testing and fixed along the way:
  `status.ps1` gave a false "not registered" for the SYSTEM-owned task
  when queried non-elevated (`Get-ScheduledTask` silently omits what
  it can't read; `schtasks`'s distinct "Access is denied" vs. "cannot
  find" wording now disambiguates); the shared token's charset included
  `%`/`^`, which `cmd.exe` silently strips when `config.bat` is
  `call`ed -- desynced the server's real token from every client for
  as long as the box had been up (also prompted flipping the token to
  opt-in by default -- see #18); and `start_tray.bat` invoking
  `pythonw.exe` directly (rather than via `start`) made the calling
  terminal block until the tray app was quit. Verified end-to-end on
  the GPU box and reconnected the remote client after the token fix.
- [#16](https://github.com/andresest83/kubundictate/issues/16)
  **Client feedback beyond clipboard + beep** (`priority: medium`) --
  open design question, not yet scoped: does the client need a visual
  surface (WisprFlow-style always-on-top popup showing the
  transcription) beyond today's audio cues + tray icon color? Filed
  separately from #15 so the cleanup work doesn't wait on this
  open-ended one. Not yet started.
- [#18](https://github.com/andresest83/kubundictate/issues/18)
  **Multi-machine auth is impractical** (`priority: medium`) -- even
  after #15's fixes, pairing a new client still means reading a
  24-char string off one screen and typing it into another. Not
  scoped: shorter tokens, QR pairing, or leaning on LAN auto-discover
  (mentioned in #8's discussion, not yet its own issue) for a
  confirm-a-short-code pairing flow instead of copy-typing.
- [#5](https://github.com/andresest83/kubundictate/issues/5)
  **Auto-paste vs. clipboard-only** (`priority: medium`, see Product
  notes) -- investigate a Windows `SendInput`-based auto-paste option
  as an alternative to copy-then-manual-Ctrl+V.
- [#7](https://github.com/andresest83/kubundictate/issues/7) **Process
  hygiene** (`priority: low`, see Product notes) -- CI lint gate, PR
  template with a test checklist, issue templates, CONTRIBUTING.md,
  docs-only-PR path filter to skip CI.
- [#6](https://github.com/andresest83/kubundictate/issues/6) **LLM
  cleanup pass** (`priority: lowest`, see Product notes) -- optional
  post-processing step that sends the raw transcript + a configurable
  system prompt to a local/cloud OpenAI-compatible endpoint before
  returning text. Deprioritized further after real-world testing showed
  raw faster-whisper output is already clean without it.

## Files

See [README.md](README.md#files).
