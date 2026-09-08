#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) for the Codex Reviewer and Validator agents.

Codex Reviewer: read-only shell (git diff/log/show, cat, grep, ..., and the
codex_review.py / review_gate.py wrappers). Validator: the same plus test
runners. Anything else - and any redirect / in-place edit / git write - is
denied. The allow-list lives in .claude/rnd-policy.json -> reviewerShell.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command", "") or ""
    agent = payload.get("agent_type") or os.environ.get("RND_AGENT") or ""
    if len(sys.argv) > 1 and sys.argv[1] == "--agent" and len(sys.argv) > 2:
        agent = sys.argv[2]
    if not agent:
        return 0
    try:
        import safety_check  # type: ignore
        ok, why = safety_check.check_reviewer_command(command, agent.lower())
    except Exception as exc:
        sys.stderr.write(f"[reviewer-shell-guard] policy error, denying: {exc}\n")
        return 2
    if ok:
        return 0
    sys.stderr.write(f"[reviewer-shell-guard] DENIED for '{agent}': {why}\nCommand: {command[:200]}\n"
                     "This agent is read-only. Report the problem instead of changing files.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
