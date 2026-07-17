# OVERNIGHT REPORT — OOAA

Autonomous overnight run. Iron rules: mock demo is sacred (revert on breakage);
`main` always releasable (dev on `overnight`, merge only after full-green
regression); live budget fuse ($15 / ≤25 runs / ≤15 steps).

Environment at start: `OPENROUTER_API_KEY` set (no Anthropic/OpenAI); `LIVE_MODEL`
unset; `mini-swe-agent` not installed. Live tasks route through OpenRouter with a
cheap default model.

## Status

- **T0 push main + overnight branch** — DONE. `.gitignore` hardened (`.env`/keys);
  no secret-like files tracked; `git push -u origin main` succeeded; `origin/main`
  == local (`e7e8858`); branch `overnight` created.
- **T1 M9a trap_stale (+trap_taint)** — DONE, merged to main (`2d17a97`). trap_stale:
  green → reopen N1 → artifact-closure verified→stale (STALE_CASCADE ×6: N2,N3,N4,
  N4e,N5,N6) → auto re-run → re-green, exit 0. trap_taint: TAINT_INVALIDATION on
  N3+N4e (readings) with N4 training SPARED (0 incidents, no re-train). Dashboard
  buttons + ▶ DEMO+ (extended playlist), default playlist untouched (rule F).
  Evidence: `docs/dashboard_stale.png`. Regression: pytest 45 + 7 scenarios exit 0.
- **T2 M9b live planner** — DONE. `run.py --plan "<Q>"` → one OpenRouter call
  (`openai/gpt-4o-mini`, key from env) → graph JSON → schema.validate + normalizer
  → `runs/<ts>-plan/plan_live.json`; usable via `--mock --plan-file`; graceful
  fallback to cached on any failure (no key / network / parse / invalid). Verified:
  real generation valid=true, **cost $0.0007**; `--mock green --plan-file <live>`
  runs green; no-key → fallback_cached. Running live spend ≈ **$0.0007 / $15**.
- **T3 M8a live worker** — pending.
- **T4 M8b live decoys** — pending (only if T3 DONE).
- **T5 M9c pitch package** — pending.
- **T6 regression + merge + report** — pending.

_(evidence and final checklist appended as tasks complete)_
