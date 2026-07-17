#!/usr/bin/env python3
"""Deterministic mock trainer (compute_phase stand-in for a long node).

Emits metrics.jsonl {"step":int,"dev_metric":float} and a checkpoint file
ckpt/ckpt_<pct>.txt every 10% of steps. dev_metric is a pure function of the
step fraction; sleep only paces output, it never affects a value.

Profiles:
  rise_cross    crosses the 0.6041 baseline near ~70%, saturates ~0.62  (green: positive)
  rise_plateau  saturates ~0.53 by ~40% (< 0.6041)                      (plateau: negative)
  hang          rises to HANG_AT then stops advancing `step`          (hung: HUNG_RESTART)
"""
import argparse
import json
import math
import os
import time

STEPS = 100
SLEEP = 0.03            # per-step pacing; total run ~3s
CKPT_EVERY = 10         # steps (== every 10%)
HANG_AT = 20            # hang profile stalls after this step
HANG_HOLD_S = 20.0      # bounded safety hold; orchestrator kills far sooner


def dev(profile: str, pct: float) -> float:
    if profile in ("rise_cross", "hang"):
        # steady climb: crosses 0.6041 at ~67%, ends 0.72; per-ckpt gain 0.042 > eps
        # so a rising run never trips PLATEAU (only a below-target saturation does).
        return 0.30 + 0.42 * pct
    if profile == "rise_plateau":
        # ~0.505/0.526/0.530/0.531 at 10/20/30/40%, asymptote 0.531 (< 0.6041)
        return 0.40 + 0.131 * (1.0 - math.exp(-16.0 * pct))
    raise SystemExit(f"unknown profile {profile}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--steps", type=int, default=STEPS)
    ap.add_argument("--sleep", type=float, default=SLEEP)
    args = ap.parse_args()

    os.makedirs("ckpt", exist_ok=True)
    with open("metrics.jsonl", "a", encoding="utf-8") as f:
        for step in range(1, args.steps + 1):
            if args.profile == "hang" and step > HANG_AT:
                time.sleep(HANG_HOLD_S)      # stop advancing step; hold then exit
                return
            d = round(dev(args.profile, step / args.steps), 4)
            f.write(json.dumps({"step": step, "dev_metric": d}) + "\n")
            f.flush()
            if step % CKPT_EVERY == 0:
                pct = step * 100 // args.steps
                with open(f"ckpt/ckpt_{pct}.txt", "w", encoding="utf-8") as c:
                    c.write(f"step={step}\ndev={d}\n")
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
