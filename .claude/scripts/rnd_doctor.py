#!/usr/bin/env python3
"""rnd_doctor.py - health check for the ai-rnd-workspace engine.

  python3 .claude/scripts/rnd_doctor.py [--json]

Exit 0 = healthy, 1 = warnings only, 2 = failures.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rndlib  # noqa: E402
from rndlib import ROOT, read_json  # noqa: E402

REQUIRED_FILES = [
    "CLAUDE.md", "README.md", ".gitignore", "VERSION", "CHANGELOG.md", "LICENSE",
    ".claude/settings.json", ".claude/rnd-policy.json", ".claude/pytest.ini",
    ".claude/agents/researcher.md", ".claude/agents/critic.md", ".claude/agents/claim-verifier.md",
    ".claude/agents/experiment-designer.md", ".claude/agents/builder.md", ".claude/agents/isolated-builder.md",
    ".claude/agents/codex-reviewer.md", ".claude/agents/validator.md",
    ".claude/skills/rnd-orchestrator/SKILL.md", ".claude/skills/rnd-case/SKILL.md",
    ".claude/skills/review-convergence/SKILL.md", ".claude/skills/knowledge-promotion/SKILL.md",
    ".claude/hooks/safety-gate.py", ".claude/hooks/builder-write-guard.py", ".claude/hooks/reviewer-shell-guard.py",
    ".claude/rules/rnd.md", ".claude/rules/review.md",
    ".codex/config.toml",
    ".claude/scripts/rnd.py", ".claude/scripts/rnd_doctor.py", ".claude/scripts/codex_review.py",
    ".claude/scripts/review_gate.py", ".claude/scripts/safety_check.py", ".claude/scripts/generate_index.py",
    ".claude/scripts/rndlib.py",
    ".claude/schemas/case.schema.json", ".claude/schemas/evidence.schema.json", ".claude/schemas/findings.schema.json",
    ".claude/schemas/experiment.schema.json", ".claude/schemas/codex-review-output.schema.json",
]


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []  # (level, name, detail)

    def ok(self, name: str, detail: str = "") -> None:
        self.items.append(("OK", name, detail))

    def warn(self, name: str, detail: str = "") -> None:
        self.items.append(("WARN", name, detail))

    def fail(self, name: str, detail: str = "") -> None:
        self.items.append(("FAIL", name, detail))


def check_tooling(r: Report) -> None:
    ver = rndlib.engine_version()
    (r.ok if __import__("re").fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", ver) else r.fail)("engine version", repr(ver) + " (VERSION must be a bare semver line)")
    v = sys.version_info
    (r.ok if v >= (3, 10) else r.fail)("python", f"{v.major}.{v.minor}.{v.micro}")
    codex = shutil.which("codex")
    if codex:
        try:
            ver = subprocess.run([codex, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
            r.ok("codex CLI", ver)
        except Exception as exc:  # noqa: BLE001
            r.warn("codex CLI", f"found but --version failed: {exc}")
    else:
        r.fail("codex CLI", "not in PATH - Codex review rounds cannot run")
    if shutil.which("timeout"):
        r.ok("timeout")
    else:
        r.fail("timeout", "coreutils timeout missing")
    g = rndlib.git("rev-parse", "--is-inside-work-tree")
    (r.ok if g.returncode == 0 else r.fail)("git repository", g.stdout.strip() or g.stderr.strip())
    try:
        import jsonschema  # noqa: F401
        r.ok("jsonschema", "installed (full validation)")
    except ImportError:
        r.warn("jsonschema", "not installed - using built-in minimal validator")


def check_layout(r: Report) -> None:
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).exists()]
    if missing:
        r.fail("required files", "missing: " + ", ".join(missing))
    else:
        r.ok("required files", f"{len(REQUIRED_FILES)} present")
    for d in (".rnd/knowledge/shared", ".rnd/knowledge/candidates", ".rnd/cases"):
        (r.ok if (ROOT / d).is_dir() else r.fail)(f"dir {d}")
    for h in (ROOT / ".claude" / "hooks").glob("*.py"):
        if not os.access(h, os.X_OK):
            r.warn(f"hook {h.name}", "not executable (chmod +x)")


def check_policy_and_settings(r: Report) -> None:
    try:
        pol = rndlib.load_policy()
        r.ok("rnd-policy.json", f"maxRounds={pol['review']['maxRounds']} maxAgents={pol['concurrency']['maxAgents']}")
    except Exception as exc:  # noqa: BLE001
        r.fail("rnd-policy.json", str(exc))
        return
    try:
        s = read_json(ROOT / ".claude" / "settings.json")
        cmds = []
        for ev, groups in (s.get("hooks") or {}).items():
            for g in groups:
                for h in g.get("hooks", []):
                    cmds.append((ev, h.get("command", "")))
        for ev, cmd in cmds:
            for part in cmd.split():
                if part.endswith(".py"):
                    p = part.replace("$CLAUDE_PROJECT_DIR", str(ROOT)).replace("${CLAUDE_PROJECT_DIR}", str(ROOT)).strip('"')
                    if not Path(p).exists():
                        r.fail(f"settings hook {ev}", f"references missing file {part}")
        r.ok("settings.json", f"{len(cmds)} hook command(s)")
    except Exception as exc:  # noqa: BLE001
        r.fail("settings.json", str(exc))
    # agents frontmatter sanity
    for a in sorted((ROOT / ".claude" / "agents").glob("*.md")):
        txt = a.read_text(encoding="utf-8", errors="ignore")
        if not txt.startswith("---") or "name:" not in txt.split("---")[1] or "description:" not in txt.split("---")[1]:
            r.fail(f"agent {a.name}", "frontmatter must have name + description")
    # hook self-test
    tests = [
        (".claude/hooks/safety-gate.py", {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}, 2),
        (".claude/hooks/safety-gate.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}}, 0),
        (".claude/hooks/builder-write-guard.py", {"tool_name": "Write", "tool_input": {"file_path": ".claude/scripts/rnd.py"}, "agent_type": "builder"}, 2),
        (".claude/hooks/builder-write-guard.py", {"tool_name": "Write", "tool_input": {"file_path": ".rnd/cases/RND-20260101-001-x/artifacts/a.py"}, "agent_type": "builder"}, 0),
        (".claude/hooks/reviewer-shell-guard.py", {"tool_name": "Bash", "tool_input": {"command": "git diff"}, "agent_type": "codex-reviewer"}, 0),
        (".claude/hooks/reviewer-shell-guard.py", {"tool_name": "Bash", "tool_input": {"command": "rm x"}, "agent_type": "codex-reviewer"}, 2),
    ]
    bad = []
    for hook, payload, expected in tests:
        p = subprocess.run([sys.executable, str(ROOT / hook)], input=json.dumps(payload), capture_output=True, text=True,
                           env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)})
        if p.returncode != expected:
            bad.append(f"{hook.split('/')[-1]} {payload['tool_input']} -> {p.returncode} (want {expected})")
    (r.ok if not bad else r.fail)("hook self-test", "; ".join(bad) if bad else f"{len(tests)} checks")


def check_schemas_and_cases(r: Report) -> None:
    for s in ("case", "evidence", "findings", "experiment"):
        try:
            read_json(rndlib.SCHEMA_DIR / f"{s}.schema.json")
            r.ok(f"schema {s}")
        except Exception as exc:  # noqa: BLE001
            r.fail(f"schema {s}", str(exc))
    n_bad = 0
    n = 0
    for d in rndlib.case_dirs():
        n += 1
        try:
            c = read_json(d / "case.json")
            errs = rndlib.validate("case", c)
            if errs:
                n_bad += 1
                r.fail(f"case {d.name}", "; ".join(errs[:3]))
            if c["id"] != d.name[:16]:
                r.fail(f"case {d.name}", f"id {c['id']} does not match directory")
            ev = d / "research" / "evidence.json"
            if ev.exists():
                e = rndlib.validate("evidence", read_json(ev))
                if e:
                    r.fail(f"evidence {d.name}", "; ".join(e[:3]))
            for x in (d / "experiments").glob("EXP-*/manifest.json"):
                e = rndlib.validate("experiment", read_json(x))
                if e:
                    r.fail(f"experiment {d.name}/{x.parent.name}", "; ".join(e[:3]))
            for x in (d / "reviews").glob("round-*/findings.json"):
                e = rndlib.validate("findings", read_json(x))
                if e:
                    r.fail(f"findings {d.name}/{x.parent.name}", "; ".join(e[:3]))
        except Exception as exc:  # noqa: BLE001
            n_bad += 1
            r.fail(f"case {d.name}", str(exc))
    r.ok("cases", f"{n} case dir(s), {n_bad} invalid")
    generated = [rndlib.RND_ROOT / "index.json", rndlib.RND_ROOT / "INDEX.md", rndlib.KNOWLEDGE_DIR / "catalog.json"]
    if not all(g.exists() for g in generated):
        subprocess.run([sys.executable, str(rndlib.SCRIPTS_DIR / "generate_index.py"), "--quiet"], capture_output=True, text=True)
        r.ok("index", "generated (was missing - normal on a fresh clone)")
        return
    chk = subprocess.run([sys.executable, str(rndlib.SCRIPTS_DIR / "generate_index.py"), "--check"], capture_output=True, text=True)
    (r.ok if chk.returncode == 0 else r.warn)("index freshness", chk.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = Report()
    check_tooling(r)
    check_layout(r)
    check_policy_and_settings(r)
    check_schemas_and_cases(r)
    fails = [i for i in r.items if i[0] == "FAIL"]
    warns = [i for i in r.items if i[0] == "WARN"]
    if a.json:
        print(json.dumps({"root": str(ROOT), "items": [{"level": l, "name": n, "detail": d} for l, n, d in r.items], "fails": len(fails), "warns": len(warns)}, indent=2))
    else:
        print(f"rnd doctor - {ROOT} (engine {rndlib.engine_version()})")
        for l, n, d in r.items:
            print(f"  [{l:4}] {n}" + (f": {d}" if d else ""))
        print(f"\n{len(fails)} failure(s), {len(warns)} warning(s)")
    return 2 if fails else (1 if warns else 0)


if __name__ == "__main__":
    sys.exit(main())
