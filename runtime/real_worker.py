"""LiveAgentWorker — a compact real coding agent (the workbook's bash-loop
fallback, since mini-swe-agent is not installed here).

An LLM writes ONE bash command per turn; we run it in the node's sandbox dir and
feed the output back, until the node's manifest exists or a step/budget cap is
hit. This is a drop-in that observes world-state — the supervisor cannot tell it
from the mock worker. That is the product claim: "drop-in, don't touch your agent".

Safety (this runs unattended on a real machine): allowlisted command names +
content denylist (no rm/network/sudo/parent-escape/home/system paths) + per-command
timeout + cwd pinned to the node dir + max_steps<=15. Model from LIVE_MODEL (cheap
default); key from OPENROUTER_API_KEY (never hardcoded/printed).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"
CMD_TIMEOUT = 25

_ALLOW = {"ls", "cat", "head", "tail", "wc", "grep", "find", "sort", "uniq",
          "awk", "sed", "echo", "pwd", "python", "python3", "true", "nl", "cut"}
_DENY = ("rm ", "rm-", "rmdir", "shutil", "os.remove", "os.unlink", "os.system",
         "os.popen", "subprocess", "sudo", "/etc/", "/system/", "/usr/", "/bin/",
         "expanduser", "socket", "urllib", "requests", "http://", "https://",
         "curl ", "wget ", "ssh ", "scp ", "git ", "pip", "brew ", "apt ", "conda ",
         "mkfs", "dd if", ":(){", "chmod", "chown", "kill ", "shutdown", "reboot",
         "__import__", "..", "~", "> /", ">/", "eval(", "exec(")

_SYSTEM = (
    "You are a careful coding agent. You act ONLY by emitting bash commands. Each "
    "turn: one short THOUGHT line, then exactly one ```bash ...``` block with a "
    "SINGLE command. Stay strictly inside the task; do not delete files, use the "
    "network, or leave your working directory. When the goal file is written and "
    "valid, reply with the single word DONE."
)

_BASH_RE = re.compile(r"```(?:bash|sh)?\s*\n?(.*?)```", re.DOTALL)


def _extract_cmd(reply: str) -> str | None:
    m = _BASH_RE.search(reply)
    if not m:
        return None
    cmd = m.group(1).strip()
    return cmd or None


def _safe(cmd: str) -> tuple[bool, str]:
    low = cmd.lower()
    for bad in _DENY:
        if bad in low:
            return False, f"denied pattern {bad!r}"
    head = cmd.strip().split()[0] if cmd.strip() else ""
    head = head.split("/")[-1]                       # allow /abs/path/python
    if head not in _ALLOW:
        return False, f"command {head!r} not in allowlist"
    return True, ""


class LiveAgentWorker:
    def __init__(self, max_steps: int = 15, model: str | None = None):
        self.max_steps = max(1, min(int(max_steps), 15))
        self.model = model or os.environ.get("LIVE_MODEL") or DEFAULT_MODEL
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY unset (live mode)")
        self.cost = 0.0
        self.steps = 0
        self.transcript: list[dict] = []

    def _chat(self, messages: list[dict], max_tokens: int = 400) -> str:
        payload = {"model": self.model, "messages": messages,
                   "temperature": 0.1, "max_tokens": max_tokens}
        req = urllib.request.Request(
            OPENROUTER_URL, data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json", "X-Title": "OOAA-agent"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        if "error" in data:
            raise RuntimeError(str(data["error"])[:200])
        usage = data.get("usage") or {}
        self.cost += usage.get("cost") or 0.0
        return data["choices"][0]["message"].get("content") or ""

    def _run(self, cmd: str, cwd: Path) -> str:
        try:
            p = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True,
                               text=True, timeout=CMD_TIMEOUT,
                               env={**os.environ, "PYTHONHASHSEED": "0"})
            out = (p.stdout + p.stderr).strip()
            return f"(exit {p.returncode})\n{out[:1500]}"
        except subprocess.TimeoutExpired:
            return "(timeout)"
        except Exception as e:  # pragma: no cover
            return f"(error {e})"

    def run_node(self, task: str, scope_dir: Path, done_check) -> dict:
        scope_dir = Path(scope_dir)
        scope_dir.mkdir(parents=True, exist_ok=True)
        messages = [{"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": task}]
        for step in range(self.max_steps):
            self.steps += 1
            reply = self._chat(messages)
            messages.append({"role": "assistant", "content": reply})
            cmd = _extract_cmd(reply)
            if cmd is None:
                if done_check():
                    break
                messages.append({"role": "user",
                                 "content": "Emit ONE ```bash``` command, or the task is not done."})
                continue
            ok, why = _safe(cmd)
            obs = f"REFUSED (safety): {why}" if not ok else self._run(cmd, scope_dir)
            self.transcript.append({"step": step + 1, "cmd": cmd, "obs": obs[:400]})
            done = done_check()
            messages.append({"role": "user",
                             "content": f"$ {cmd}\n{obs}\n\n(step {step + 1}/{self.max_steps})"
                                        + (" Goal file is valid — reply DONE." if done else "")})
            if done:
                break
        return {"steps": self.steps, "cost": round(self.cost, 6),
                "done": done_check(), "model": self.model, "transcript": self.transcript}


def chat_once(system: str, user: str, model: str | None = None) -> tuple[str, float]:
    """One stateless LLM call (N5 analysis / N6 report polish). Returns (text, cost)."""
    w = LiveAgentWorker(max_steps=1, model=model)
    text = w._chat([{"role": "system", "content": system},
                    {"role": "user", "content": user}], max_tokens=1200)
    if not text.strip():
        raise RuntimeError("empty completion")
    return text, w.cost
