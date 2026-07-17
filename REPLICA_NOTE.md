# REPLICA_NOTE

Replica of `https://github.com/xesws/OOAA.git` → `https://github.com/xesws/Loop_ENG_Hackathon.git`, created 2026-07-17 (PDT). No code, logic, or file content was modified. Verified runnable on macOS (Apple Silicon), Python 3.9.12.

## Method (deviation from the flat-copy variant)

- Used the **mirror variant** allowed by the task brief (`git clone --mirror` + `git push --mirror`), preserving the full commit history and all 3 branches (`main`, `frontend-night`, `overnight`) instead of a single squashed "replica" commit.
- **Commit timestamps rewritten (explicit user requirement):** all 20 commits now carry author date == committer date, evenly spaced in **2026-07-17 11:00:00–11:29:46 PDT** (94 s apart, oldest-first in topological order). Commit hashes therefore differ from upstream; trees, messages, and authors are unchanged.
- The flat-copy exclusion list (`.git`, `runs/`, `__pycache__`, `.env`, `*.log`) was not applicable to the mirror path. Verified beforehand that no `.env`, logs, or secret-looking files are tracked on any branch, so nothing sensitive was pushed.
- Dependencies were installed into a local `.venv/` (not global `pip install`): `networkx pyyaml pytest pytest-asyncio rich`. The repo has no `requirements.txt`.

## Verification results (all three gates pass)

a. `pytest -q` → **45 passed** in 0.40s.

b. Seven scenarios, each `python run.py --mock --scenario <s>` → **exit 0**:
   `green`, `trap_b`, `trap_scope`, `plateau`, `hung`, `trap_stale`, `trap_taint`.

c. `python run.py --serve` → dashboard serves at `http://127.0.0.1:8000/` (HTTP 200).
   The ▶DEMO button performs `POST /demo`; triggered headlessly and monitored via `GET /demo/status`:
   - Scene 1 `plateau`: replay advanced through all 25 frames.
   - Scene 2 `trap_scope`: replay advanced through all 9 frames.
   - Playlist finished, controller back to `idle`.
   - All frontend-consumed endpoints return 200 + valid JSON: `/`, `/state.json`, `/plan_cached.json`, `/demo/status`, `POST /demo`, `POST /demo/ctl`.
   - Server produced **zero error output** during the full run (request logging is intentionally muted at `run.py:333`; any handler exception would have printed a traceback — none did). The frontend talks to the backend exclusively through the endpoints above, all verified 200/valid, so no browser-console errors are expected; the page was also opened in a browser for a visual pass.

## Known differences vs. upstream repo

- Commit hashes and dates only (see above). File contents are byte-identical to upstream `main` (`b6e740d` tree).
