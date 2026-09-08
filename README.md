# ai-rnd-framework

**Engine version:** see [`VERSION`](VERSION) (semver) and [`CHANGELOG.md`](CHANGELOG.md). Releases are tagged `vX.Y.Z`.

> Multi-agent AI workspace for technical R&D, experimentation, review convergence, validation, and reusable knowledge.

This repository is the **framework**: the engine plus its documentation, with no R&D data. You copy it once and it becomes *your* permanent R&D workspace, where your cases are committed alongside it. See [Use it as your own workspace](#use-it-as-your-own-workspace).

One Git repository is the permanent R&D workspace. Every topic (AWS, Linux, Kubernetes, GPU, LLM, Claude Code, Codex, databases, networks, security, OSS, PoCs...) is an **R&D Case** under `.rnd/cases/`, not a separate repository. Claude Code acts as the R&D Lead and orchestrates specialised subagents; Codex CLI provides independent code review; every case leaves evidence, reproducible experiments, reviewed implementation, validated results and a documented decision behind.

Everything except the top-level documents lives in dot-directories, so the working tree stays clean and the whole workspace is easy to ignore (`.rnd/` for the data alone, `.claude/ .codex/ .rnd/` for everything).

```
ai-rnd-workspace/
├── README.md  SPEC.md  CLAUDE.md  CHANGELOG.md  VERSION   # the only visible files
├── .claude/          R&D Engine
│   ├── agents/  skills/  hooks/  rules/  settings.json  rnd-policy.json
│   └── scripts/  schemas/  tests/  pytest.ini
├── .codex/           Codex CLI settings
└── .rnd/             R&D data
    ├── index.json  INDEX.md
    ├── cases/       RND-YYYYMMDD-NNN-<slug>/ ...
    └── knowledge/   shared/  candidates/  catalog.json
```

Paths come from `.claude/rnd-policy.json` → `layout`, which `.claude/scripts/rndlib.py` reads. Moving the data directory is a policy edit; moving `.claude/` itself also needs the hook commands in `.claude/settings.json` updated, because Claude Code resolves those before the policy is read.

Full design: [`SPEC.md`](SPEC.md). Operating manual for Claude Code: [`CLAUDE.md`](CLAUDE.md).

## Requirements
- Python 3.10+ (no third-party packages required; `jsonschema` optional for stricter validation)
- Git, coreutils `timeout`
- `pytest` only to run the engine tests (`pip install pytest`, or `uv run --no-project --with pytest ...`)
- [Claude Code](https://code.claude.com) (project settings in `.claude/`)
- [Codex CLI](https://github.com/openai/codex) on `PATH` (`codex exec` is used for review rounds)

## Use it as your own workspace

```bash
# 1. take a copy (GitHub: "Use this template", or a plain clone)
git clone https://github.com/nix-tkobayashi/ai-rnd-framework.git my-rnd-workspace
cd my-rnd-workspace && rm -rf .git && git init -b main

# 2. check the engine on your machine
python3 .claude/scripts/rnd.py doctor        # tooling, hooks, schemas, policy
python3 -m pytest .claude/tests -q           # 115 engine tests

# 3. start working - your cases are committed with the engine from here on
python3 .claude/scripts/rnd.py new "<title>" --question "<your question>"
```

`.rnd/cases/` and `.rnd/knowledge/` ship empty on purpose: the framework carries no R&D data, and **your** cases are meant to be tracked in your copy (SPEC 33/45 - the case history and the knowledge are the output). Only the generated index (`.rnd/index.json`, `.rnd/INDEX.md`, `.rnd/knowledge/catalog.json`) stays untracked; `rnd.py doctor` recreates it on a fresh clone.

Optional local tuning: `CLAUDE.local.md` (machine-specific notes) and `.claude/settings.local.json` are git-ignored.

The framework was validated before release by running one complete case through it end to end (35 evidence items, a 14-criterion experiment, three Codex review rounds until convergence, an independent validation, a recorded decision). That case is not shipped: it contained machine-specific paths, and a framework repository should carry no R&D data. `.claude/skills/rnd-orchestrator/SKILL.md` describes each step, and `.claude/tests/` exercises the whole state machine with a stubbed Codex.

## Quick start
```bash
python3 .claude/scripts/rnd.py doctor                     # engine health check
python3 .claude/scripts/rnd.py search "nvidia pair"       # look for an existing case first
python3 .claude/scripts/rnd.py new "NVIDIA PAIR evaluation" --type experiment --tags nvidia,gpu --question "Is PAIR usable for ...?"
python3 .claude/scripts/rnd.py resume RND-20260908-001    # resumable from any new session
```
Inside Claude Code: `/rnd-orchestrator <your question>` runs the whole workflow; `/rnd-case`, `/review-convergence`, `/knowledge-promotion` cover the parts.

## Workflow
```
User question → R&D Lead → existing-case search → resume | create
  → Researchers (≤3) ∥ Critics (≤2) → synthesis (facts) → Experiment design
  → Builder (baseline tests first) → Codex review ⇄ Claude fix (tests before every round; ≤5 rounds; oscillation detection)
  → Validator (behaviour / acceptance criteria / reproducibility) → Decision (≠ research) → Archive → Knowledge promotion
```

### What the guardrails do and do not do

The PreToolUse hooks (`safety-gate`, `builder-write-guard`, `reviewer-shell-guard`) block destructive commands and keep each agent inside its write boundary. They parse shell text, so they are **defence in depth, not a sandbox**: they stop the mistakes an agent actually makes, not a determined attempt to get around them. The one real sandbox in the loop is Codex, which runs with `-s read-only`. Run this framework on code you are willing to have an agent modify, and keep the Claude Code permission settings as the outer boundary.

## Key guarantees
| Principle | Enforced by |
|-----------|-------------|
| Researcher/Critic and Builder/Reviewer/Validator are different agents | `.claude/agents/*.md`, orchestrator skill |
| Claude-written code is reviewed by Codex; Claude cannot close a finding; every fix goes back to Codex | `.claude/scripts/codex_review.py`, `rnd.py finding set` (Claude may only set `fixed_pending_review` / `disputed`) |
| Convergence rules (0 actionable findings + tests PASS; 2× CLEAN for high risk; maxRounds 5; no forced PASS) | `.claude/scripts/review_gate.py`, `.claude/rnd-policy.json` |
| Oscillation (same finding re-opened) escalates to the Lead | fingerprints + `reopenCount` in `findings.json` |
| Codex runs read-only; agent roles have write boundaries enforced on the common paths | Codex `-s read-only` (a real sandbox) plus `.claude/hooks/*.py` PreToolUse hooks (defence in depth, not a sandbox - see below) |
| Case files are the single source of truth, resumable from any session | `.rnd/cases/<CASE>/case.json`, `rnd.py resume`, `handoff.md` |
| Evidence carries provenance and freshness; stale evidence is flagged | `.claude/schemas/evidence.schema.json`, `rnd.py evidence check` |
| Knowledge is promoted deliberately, never automatically | `.rnd/knowledge/candidates/` → review → `.rnd/knowledge/shared/` |

## Scripts
| Script | Purpose |
|--------|---------|
| `.claude/scripts/rnd.py` | case lifecycle CLI (new/search/resume/state/research/report/agent/evidence/experiment/review/findings/tests/validate/decide/archive/index) |
| `.claude/scripts/codex_review.py` | one Codex review round: tests → `codex exec` (read-only, JSON schema) → merge findings → gate |
| `.claude/scripts/review_gate.py` | convergence verdict: CONVERGED / NOT_CONVERGED / FAILED_TO_CONVERGE / REVIEW_OSCILLATION |
| `.claude/scripts/safety_check.py` | command / path / secret / diff checks shared by the hooks |
| `.claude/scripts/generate_index.py` | regenerates `.rnd/index.json`, `.rnd/INDEX.md`, `.rnd/knowledge/catalog.json` |
| `.claude/scripts/rnd_doctor.py` | health check of tooling, layout, policy, hooks, schemas, cases |
| `.claude/scripts/rndlib.py` | shared helpers (paths, schema validation, state machine, git) |

Version: `python3 .claude/scripts/rnd.py --version`. Engine tests: `python3 -m pytest .claude/tests -q` (or without a system pytest: `uv run --no-project --with pytest -- python -m pytest .claude/tests -q`).
