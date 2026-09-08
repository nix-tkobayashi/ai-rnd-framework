#!/usr/bin/env python3
"""PreToolUse hook (matcher: Bash) for every agent including the Lead.

Blocks destructive / irreversible shell commands defined in
.claude/rnd-policy.json -> safety.blockedCommandPatterns, and (when running
inside a Builder subagent) shell-level writes to protected R&D infrastructure
paths. Exit code 2 + stderr message = deny.
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
        return 0  # never block on malformed input
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command", "") or ""
    agent = payload.get("agent_type") or os.environ.get("RND_AGENT") or ""
    if len(sys.argv) > 1 and sys.argv[1] == "--agent" and len(sys.argv) > 2:
        agent = sys.argv[2]
    try:
        import safety_check  # type: ignore
        ok, why = safety_check.check_command(command, agent, cwd=payload.get("cwd"))
    except Exception as exc:  # policy unreadable -> fail closed only for obviously destructive commands
        ok, why = ("rm -rf /" not in command and "git push --force" not in command), f"safety-gate fallback ({exc})"
    if ok:
        return 0
    sys.stderr.write(f"[safety-gate] DENIED: {why}\nCommand: {command[:200]}\n"
                     "If this is genuinely required, the human user must run it manually.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
