# reliability-cleanup | thread: deskflow-hardening | status: active | Implement a bounded latest-wins clipboard pipeline for screenshot bursts on an isolated branch.

## What changed
- `docs/superpowers/specs/2026-07-11-clipboard-reliability-phase-1-design.md` — committed an initial broad clipboard reliability design at `8799e09`; later evidence narrowed the desired implementation to screenshot burst backpressure.
- Created branch `fix/clipboard-latest-wins` from `8799e09`.
- No DeskFlow source or test files have been changed.

## What works (verified)
- Branch isolation exists — `git branch --show-current` → `fix/clipboard-latest-wins`.
- Current revision is readable — `git rev-parse --short HEAD` → `8799e09`.
- The user reports that ordinary raw-text and single-image clipboard synchronization works during normal use.

## Broken or open
- **Rapid screenshots can make paste unavailable and may contribute to disconnects** — the user reproduced the symptom by taking many screenshots quickly. Server logs showed repeated clipboard injections and later `[WinError 10054]`, but the remote client log was not captured, so the disconnect's exact cause remains unproven. Next: implement and test bounded latest-wins scheduling, then repeat the two-machine reproduction with logs from both machines.
- **The committed spec is broader than the approved implementation** — it proposes message IDs, acknowledgements, and protocol hardening without a reproduced need. Next: revise it to preserve the existing wire format and specify one active plus one replaceable pending clipboard snapshot.
- **Codex file editing is blocked** — `apply_patch` fails because `codex-windows-sandbox-setup.exe` is missing. Next: restart the Codex app/session and retry a small workspace patch before continuing.

## Key facts
- Branch: fix/clipboard-latest-wins
- Commit: 8799e09
- Parent handoff: handoffs/2026-07-11-1008-reliability-cleanup.md
- Decisions not yet captured elsewhere: when A is active and B, C, then D arrive, finish A and process D; discard B and C. Never interrupt a TCP frame already being sent. Separate clipboard observation from compression/sending so new snapshots can replace the pending slot while A is active. Preserve the current text/image/HTML/RTF payload schema for this branch.

## Resume by
1. Confirm branch `fix/clipboard-latest-wins` and verify `apply_patch` works after restarting Codex.
2. Revise `docs/superpowers/specs/2026-07-11-clipboard-reliability-phase-1-design.md` to the approved latest-wins design and commit the revision.
3. Read the writing-plans template, create the implementation plan under `docs/plans/`, then implement with failing tests first.
4. Test that an active A followed by B, C, and D delivers only A then D; also verify normal text, image, HTML, and RTF behavior remains compatible.

Open question for the user: none
