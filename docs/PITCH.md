# Graph Supervisor for Auto-Research — Pitch Package

**One line:** we built the PI (Principal Investigator) for your agent lab — a
supervisor that watches a multi-agent research graph and, using purely programmatic
signals, catches the agent that hangs, plateaus, falsely claims victory, breaks
comparability, or contaminates downstream results — and auto-remediates.

**Thesis:** *don't evaluate what the agent says — only whether the world-state
changed.* File hashes, metric trajectories, exit codes, manifest tuples. Never an
LLM judge.

---

## 1. Three-minute demo script (line-by-line, English)

> Operator note: run everything from the browser. One terminal running `--serve`.
> `▶ DEMO` (plateau → trap_scope) is the rehearsed A-path. `▶ DEMO+` adds the
> amber-wave set pieces. If the room asks "is it live?", switch to §4.

**0:00 — Hook (20s).**
"Your agent team is running a 3-hour experiment. One agent silently spins, burning
tokens. Another quietly edits the eval script so its numbers look better. A third
reports 'done, beat baseline by 5 points' — it tested on the training set. Today,
every agent framework gives you the same thing when this happens: one word,
*Timeout*. Auto-research without a supervisor is just an automated p-hacking
machine."

**0:20 — The graph (15s).** *(point at the dashboard)*
"A research question becomes a task graph: protocol → data → freeze the harness →
baseline ∥ fine-tune → analysis → report. Squares are fast agents, the circle is a
long training job, diamonds are reactive nodes. No barriers — the baseline finishes
and enters the report while training is still running. Nobody waits for the slowest
sibling."

**0:35 — The money shot: plateau (45s).** *(click ▶ DEMO)*
"Watch the fine-tuning job. Its dev score climbs… 0.50, 0.52, 0.53… and stalls
below the 0.58 baseline. Two checkpoints with no real gain — **PLATEAU_TRIP**. The
supervisor kills it *at a checkpoint boundary*, keeps the best checkpoint, and does
the thing a p-hacking machine never does: it writes the **negative result** into the
report. Then it frees the GPU and the analysis node performs **graph surgery** — it
grows a brand-new ablation node, right there on the graph, to explain the plateau.
Without a supervisor you learn all this after 3 hours. Here: 40% of the budget, and
a report that was never stale."

**1:20 — Comparability + scope (40s).** *(trap_scope auto-follows, or click trap_scope)*
"Second failure. The method agent reaches into the baseline's directory and writes a
file — out of its lane. **SCOPE_VIOLATION**: intercepted, reverted, blamed on the
culprit; the node flashes red, the incident streams up. And the classic one
*(reference trap_b / the live evidence)*: an agent 'drops noisy samples' to
stabilize its score — now its data hash no longer matches the baseline.
**COMPARABILITY_BLOCK** — the result is withheld, the baseline stands. Both caught
by hash and exit-code comparison. Zero LLM judges."

**2:00 — The amber wave (20s).** *(▶ DEMO+ → trap_stale)*
"Data bug. An upstream node reopens because it discovered duplicate samples. Its
entire downstream artifact-closure turns amber — **STALE_CASCADE** — and auto
re-runs back to green. And when the *protocol* breaks *(trap_taint)*, taint
propagates along artifact edges but **spares the training** — you re-evaluate the
readings, you don't throw away the hour of GPU."

**2:20 — Anytime report (15s).**
"Pull the plug at any moment. The report is always a complete snapshot of currently
verified knowledge. Killing anything still leaves a coherent report — with a black
box of every incident, ranked."

**2:35 — Thesis + close (25s).**
"Three rules. Don't trust what the agent says; watch the graph. Fuses on the nodes,
gates on the edges. And conflict isn't an exception — it's missing structure in the
plan, exposed at runtime, and drawn back in. We don't remove loops. We meter them.
**We built the PI for your agent lab.**"

---

## 2. Seven-slide skeleton

1. **Title** — "Graph Supervisor for Auto-Research / We built the PI for your agent
   lab." Sub: *don't trust what the agent says; watch whether the world changed.*
2. **The pain** — 5 real failure modes (spin / cheat eval / false victory / oscillate
   / silent staleness). The only signal you get today: *Timeout*.
3. **The idea** — research work is a live graph, not a linear flow. Nodes carry
   fuses (budget + progress); edges carry gates (completion truth + comparability).
   No graph-wide barrier.
4. **Live demo** — plateau → negative result + graph surgery; scope + comparability;
   amber wave. *(this is the slide you talk over the dashboard for.)*
5. **How it works** — programmatic signals only: sha256 scope fingerprints,
   `(step, best_dev)` trajectories, the comparability four-tuple, acceptance exit
   codes. Five-rung ladder: bounce → blame → invalidate-downstream → graph-surgery →
   fuse. Every rung logs an incident.
6. **Why us / why now** — AIDE optimizes *inside* one node; we supervise *between*
   nodes. Agent Laboratory is the sequential pipeline we critique. LangGraph gives
   you retries inside a node; we adjudicate the graph: whose fault, is it comparable,
   invalidate downstream, when to force a negative result.
7. **Roadmap + close** — proxy form (drop-in in front of any framework) / docker
   runtime / portfolio sweep (successive-halving fund manager). "We don't remove
   loops. We meter them."

---

## 3. Q&A crib

**"Isn't this just LangGraph / AutoGen checkpointing + retries?"**
Those are single-node fault-tolerance primitives. We operate at the *graph* level:
blame-routing across parallel siblings, comparability between experiments, stale
cascade of downstream closures, and — the one nobody else has — *forcing a negative
result when a loop is out of progress budget*. Complementary and stackable; our
roadmap is to sit as a proxy in front of them.

**"Why not use an LLM as the judge?"**
Judges get talked out of it — research puts the flip rate around ~13.6%. Every gate
here is a hash comparison or an exit code. An LLM appears in exactly two places: the
worker doing the actual work, and one optional arbitration call during graph surgery.

**"What's actually novel — the detection algorithms?"**
Not the algorithm IQ; the *supervised object*. We lifted supervision from "a linear
process" to "a task graph with cycles." blocked vs stuck vs oscillating; a
comparability gate; stale cascade; per-edge metered loops — these concepts don't
even have a definition in a linear model.

**"AIDE already does ML agent research."**
AIDE runs a tree search to optimize the code *inside one node*, and it's excellent
at that — we borrow its task format. We supervise *between* nodes: who is comparable
to whom, whose reopen invalidates whom, when to stop. Orthogonal layers.

**"Is the demo staged?"**
The mechanism is 100% real and deterministic — run it yourself. The failures are
induced by adversarial task descriptions, which is exactly chaos-engineering fault
injection, a standard safe-demo practice. And we have live evidence
(`docs/live_trap_*`) of a real agent taking the comparability bait and being caught.

**"How general is it?"**
The runtime interface is four methods (spawn / fingerprint / kill / revert) plus the
graph schema. Today we ship one implementation on purpose — a tabular research
pipeline that runs in seconds so nothing can go wrong on stage.

**"Roadmap?"**
(1) proxy form — drop in front of any agent framework, zero code change. (2) docker
/ remote runtime for real GPU jobs. (3) portfolio sweep — N configs launched
speculatively, a reactive ranker does successive halving; the supervisor becomes a
fund manager for compute.

---

## 4. "Is this live?" — the standard answer

> "The run really executes. What you're watching on stage is the recorded run played
> back at explaining-speed — same events, same incidents, deterministic. And it's not
> just a puppet show: our live planner turns your question into a validated research
> graph with one model call, a real agent produces a baseline that passes the gate,
> and *(point to `docs/live_trap_manifest.json`)* a real agent took the 'drop noisy
> samples' bait and got caught by the comparability gate. The mock path exists so the
> demo never depends on conference Wi-Fi — the mechanism is identical."

Concretely, if asked to prove it, run in the terminal:
- `python run.py --plan "<their question>"` → a validated `plan_live.json` (one LLM call).
- `python run.py --live --node N3` → a real agent writes + passes the baseline gate.

---

## 5. Demo operation checklist (venue)

- [ ] `git clone`, install deps: `pip install networkx pyyaml pytest` (rich optional).
- [ ] Sanity: `pytest -q` (45 green) and `python run.py --mock --scenario plateau` (exit 0).
- [ ] Start the dashboard: `python run.py --serve` → open `http://127.0.0.1:8000/`.
- [ ] Primary: click **▶ DEMO** (plateau → trap_scope). Watch N4 climb, turn red,
      negative result, N7 grow in; then the scope violation flash.
- [ ] Set pieces: click **▶ DEMO+** (adds trap_stale amber wave + trap_taint).
- [ ] Individual buttons available: green / trap_b / trap_scope / plateau / hung /
      trap_stale / trap_taint.
- [ ] Live proof (only if Wi-Fi + `OPENROUTER_API_KEY` set): `python run.py --plan
      "<question>"`; `python run.py --live --node N3`.
- [ ] Fallback of last resort: `python run.py --replay runs/<ts>/replay.jsonl` — the
      recording plays with zero dependencies.
- [ ] Keep it snappy: default demo pacing is ~1.2s/frame; plateau runs ~30s.
