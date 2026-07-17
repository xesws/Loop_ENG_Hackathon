# FRONTEND NIGHT — report

Goal: push the existing demo's readability and stage presence to this round's
limit. No new product features — presentation layer only. All work on branch
`frontend-night`, each tier full-regression-gated then ff-merged to `main`.

Constraints honored: only `dashboard/`, `run.py`'s serve section, and `docs/` were
touched. `core/`, `scenarios/`, `graph/`, `runtime/`, and the `state.json` schema
were not. `index.html` stays a single self-contained file (the only `http` string
is the SVG namespace URI; every fetch is localhost). The default ▶ DEMO playlist
(plateau → trap_scope) is unchanged.

## Tiers

### P1 — stage readability + self-explanatory — **DONE** (merged `ba9ec2b`)
- `?stage=1` presentation mode: bigger nodes/labels, white-ink high contrast,
  projector-readable from 3 m.
- **Narration bar** (bottom): a plain-English sentence per incident and key state
  transition (event-driven); the same sentence is also added to each incident card.
- **Node hover card**: goal / scope / budget (static per-node metadata, since
  `state.json` is frozen) + live status / laps / tokens / step / best_dev.
- **Legend upgrade**: shapes, human status phrases, and edge types with sample
  lines (solid = artifact hard dep, dashed = stream subscription, dotted = metered
  back-edge). Node status is now bold + colour-coded.
- Before/after: `docs/frontend/p1_before.png` → `p1_after.png`,
  `p1_after_stage.png`, `p1_after_hover.png`.
- **Plus `docs/WHAT_IS_THIS.md`** (P1-priority): one-page plain-language explainer.

### P2 — show choreography — **DONE** (merged `4e9a696`)
- **Replay control bar** (⏮ ▶/⏸ ⏭ 🐢 🐇) in the narration strip — the Q&A
  "replay that" tool. Server side: `_ReplayFeed` gained pause/step/back/speed and a
  `POST /demo/ctl` endpoint.
- **Key-moment freeze**: the feed auto-holds ~2 s when it lands on a
  PLATEAU_TRIP / SCOPE_VIOLATION / COMPARABILITY_BLOCK frame; the client adds a
  focus ring on the node and a red glow on that incident card.
- **Inter-scene banner** splits the title into a heading + subtitle line.
- Before/after: `docs/frontend/p2_before.png` → `p2_after.png` (control bar +
  paused + glowing key cards).

### P3 — robustness — **DONE** (merged `4892f47`)
- **Server-disconnect red bar** ("lost connection… is --serve running?"), last
  state preserved; clears on reconnect.
- **Clean refresh recovery**: a `booted` guard adopts the current incident count
  once, so a reload doesn't replay every historical incident's flash/narration.
- **No memory leak**: flash/focus counters deleted at 0; renders rebuild bounded
  DOM; the SVG hover listener is attached once.
- **Window scaling**: media queries (aside narrows ≤1200 px; graph/aside stack
  ≤860 px).
- Evidence: `docs/frontend/p3_after_disconnect.png`.

### P4 — decoration — **DONE** (this commit)
- **Edge-flow animation**: stream/back edges animate a flowing dash. The SVG is now
  split into an edge layer (rebuilt only when the node-set changes) and a node
  layer, so the flow is continuous across polls. Respects `prefers-reduced-motion`.
- **Favicon + title**: inline data-URI SVG favicon (three coloured nodes); no
  external request.
- State-transition easing was already present (`transition: fill/stroke`).
- Before/after: `docs/frontend/p4_before.png` → `p4_after.png`.

## Regression (run at every tier; final pass here)

- `pytest -q` → **45 passed**.
- 7 mock scenarios (`green/trap_b/plateau/hung/trap_scope/trap_stale/trap_taint`)
  → all **exit 0**.
- All 9 dashboard buttons wired (7 scenarios + ▶ DEMO + ▶ DEMO+); ▶ DEMO playlist
  completes (plateau → trap_scope → idle).
- Browser **console: zero errors** at every tier.
- No external resource loads (only localhost fetches + the SVG namespace URI).

## Morning 5-minute acceptance

1. `git clone` main, `pip install networkx pyyaml pytest rich`, `pytest -q` → 45.
2. `python run.py --serve` → open `http://127.0.0.1:8000/`.
3. Click **▶ DEMO** — watch the narration bar explain each moment; N4 climbs, turns
   red, the auto-freeze holds on the plateau, N7 grows in.
4. Hover any node → goal/scope/budget card. Check the legend (shapes + statuses +
   edge types).
5. Open `http://127.0.0.1:8000/?stage=1` for the projector — everything ~1.4×,
   high contrast, readable from the back of the room.
6. Q&A tool: use ⏮ / ⏸ / ⏭ to replay any moment. Kill `--serve` → the red
   "lost connection" bar appears; restart it → it clears.

Fallback of record is unchanged: the mock path + `--replay` play with zero
dependencies.
