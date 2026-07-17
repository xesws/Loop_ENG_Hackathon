# What is this? (one page, plain language)

You've been away all night. Here's the whole thing in five minutes.

## The one-sentence version

It's a **supervisor for a team of AI agents doing research**. A question like *"does
a fine-tuned small model beat a baseline?"* gets split into a **graph** of tasks, each
run by an agent. Our layer watches that graph and — using only hard signals (file
hashes, metric curves, exit codes, **never an LLM judge**) — catches the agent that
hangs, plateaus, lies about being done, breaks comparability, or contaminates
downstream results, and auto-fixes it. Thesis: **don't trust what the agent says;
watch whether the world-state actually changed.**

## What each thing on the dashboard means

- **Shapes = node kind.** ▭ square = a *fast* agent (seconds). ● circle = a *long*
  training job. ◆ diamond = a *reactive* node (wakes on events).
- **Colour = status.** blue *working* · green *verified* · grey *blocked/withheld* ·
  amber *stale (re-running)* · orange *stuck/oscillating* · red *plateaued/killed* ·
  purple *retired*.
- **Edges = dependency type.** solid = **artifact** (hard dependency — gates
  readiness). dashed = **stream** (subscription — never blocks; the baseline enters
  the report while training still runs). dotted = **metered back-edge** (a loop with
  a lap budget, "lap ≤ 3").
- **The circle's little bar** = the long job's `best_dev` climbing, with a white tick
  at the **0.58 baseline** it must beat.
- **Incident stream (right)** = the black box: every supervisor action, newest first,
  each with a plain-English line.
- **Narration bar (bottom)** = what just happened, in one sentence.
- **Hover any node** = its goal, scope (the only dir it may write), budget, and live
  laps / step / best_dev.
- **`?stage=1`** in the URL = presentation mode (bigger + higher contrast for a
  projector).

## The graph (fixed fixture)

`N0 protocol → N1 data → N2 freeze-harness → { N3 baseline ∥ N4 fine-tune (long) }
→ N4e ckpt-eval → N5 analysis → N6 report`, plus `N5→N4` a metered back-edge and
`N7` an ablation node N5 can spawn at runtime. No graph-wide barrier — that's the
point: siblings run in parallel, the baseline finishes and enters the report while
N4 is still training.

## The seven scenarios (what each one proves)

| Scenario | What you see | What it proves |
|---|---|---|
| **green** | everything turns green | the happy path: baseline + fine-tune, positive result |
| **plateau** | N4 climbs, stalls ~0.53, turns red; N7 grows in | a hopeless run is **early-stopped**, the **negative result is recorded** (anti-p-hacking), and the freed GPU funds a new ablation via **graph surgery** |
| **trap_b** | N4 turns grey, a red incident | an agent "improved" its score by changing the data → **not comparable** → result withheld, baseline stands |
| **trap_scope** | N4 flashes red | an agent wrote outside its lane → **intercepted, reverted, blamed** |
| **trap_stale** | a wave of amber, then re-green | a data bug reopens upstream → downstream **cascades to stale** and **auto re-runs** |
| **trap_taint** | N3/N4e go amber, N4 stays green | a broken protocol **voids the readings but spares the training** (the expensive part) |
| **hung** | N4 restarts, then dies | a stalled trainer is **restarted once from its checkpoint**, then killed |

Every one of these, in any other agent framework today, gives you a single word:
*Timeout*.

## Top 5 questions the judges will ask

1. **"Is this just LangGraph retries?"** No — those are single-node fault tolerance.
   We work at the *graph* level: blame across siblings, comparability between
   experiments, stale cascades, and forcing a negative result when a loop is out of
   progress budget. Complementary; our roadmap is to be a proxy in front of them.
2. **"Why not an LLM judge?"** Judges get talked out of it (~13.6% flip rate). Every
   gate here is a hash or an exit code. An LLM shows up only in the worker and one
   optional arbitration call.
3. **"Is the demo staged?"** The mechanism is 100% real and deterministic — run it
   yourself. Failures are induced by adversarial task descriptions (chaos-engineering
   fault injection). We even have live evidence of a real agent taking the bait
   (`docs/live_trap_manifest.json`).
4. **"What's actually new?"** Not the algorithm IQ — the *supervised object*: we
   lifted supervision from a linear process to a task graph with cycles. blocked vs
   stuck vs oscillating, comparability gates, stale cascade, metered loops — these
   don't even have a definition in a linear model.
5. **"How does it generalize?"** Four runtime methods (spawn / fingerprint / kill /
   revert) + the graph schema. One implementation today, on purpose, so nothing
   breaks on stage. Roadmap: proxy form, docker runtime, portfolio sweep.

*For the full 3-minute script and slide skeleton, see `docs/PITCH.md`.*
