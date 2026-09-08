#!/usr/bin/env python3
"""PreToolUse hook (matcher: Write|Edit|MultiEdit|NotebookEdit) for Builder agents.

Denies writes to R&D infrastructure (.claude/, .codex/, scripts/, schemas/,
rnd/, knowledge/ ...) so the implementation agent cannot rewrite the rules or
the Single Source of Truth. Allowed exceptions (PoC code / logs) are listed in
.claude/rnd-policy.json -> protectedPaths.builderAllowedWithinDenied.

Also used for read-only agents: any write attempt is denied.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    tool = payload.get("tool_name")
    if tool not in WRITE_TOOLS:
        return 0
    ti = payload.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path") or ti.get("path") or ""
    agent = payload.get("agent_type") or os.environ.get("RND_AGENT") or ""
    if len(sys.argv) > 1 and sys.argv[1] == "--agent" and len(sys.argv) > 2:
        agent = sys.argv[2]
    if not agent:
        return 0  # Lead session: unrestricted (it owns the management files)
    try:
        import safety_check  # type: ignore
        ok, why = safety_check.check_path_write(path, agent, cwd=payload.get("cwd"))
    except Exception as exc:
        sys.stderr.write(f"[builder-write-guard] policy error, denying write: {exc}\n")
        return 2
    if ok:
        return 0
    sys.stderr.write(f"[builder-write-guard] DENIED write by '{agent}' to {path}\nReason: {why}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
