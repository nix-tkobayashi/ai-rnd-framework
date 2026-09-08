# ai-rnd-framework

**Engine version:** see [`VERSION`](VERSION) (semver) and [`CHANGELOG.md`](CHANGELOG.md). Releases are tagged `vX.Y.Z`.

> Multi-agent AI workspace for technical R&D, experimentation, review convergence, validation, and reusable knowledge.

This repository is the **framework**: the engine plus its documentation, with no R&D data. The engine is self-contained in `.claude/` and keeps its data in `.rnd/`, so a workspace is **any Git repository that carries those two directories**: a clone of this repository used as a dedicated R&D workspace, or an existing product, service or infrastructure repository that runs its R&D cases next to its own code. See [Use it](#use-it).

Within a workspace, one repository holds all the R&D. Every topic (AWS, Linux, Kubernetes, GPU, LLM, Claude Code, Codex, databases, networks, security, OSS, PoCs...) is an **R&D Case** under `.rnd/cases/`, not a separate repository. Claude Code acts as the R&D Lead and orchestrates specialised subagents; Codex CLI provides independent code review; every case leaves evidence, reproducible experiments, reviewed implementation, validated results and a documented decision behind.

```
<any repository>/
├── (the repository's own files - README, CLAUDE.md, code ... untouched)
├── .claude/          R&D Engine            (installed by rnd.py install)
│   ├── VERSION  rnd-policy.json  settings.json  (merged into an existing one)
│   ├── agents/  skills/  hooks/  rules/
│   └── scripts/  schemas/  tests/  pytest.ini
└── .rnd/             R&D data              (yours; commit it)
    ├── index.json  INDEX.md                (generated, git-ignored)
    ├── cases/       RND-YYYYMMDD-NNN-<slug>/ ...
    └── knowledge/   shared/  candidates/  catalog.json (generated)

ai-rnd-framework/     this repository = the layout above + README.md SPEC.md CLAUDE.md CHANGELOG.md LICENSE .codex/
```

`README.md`, `SPEC.md`, `CLAUDE.md`, `CHANGELOG.md`, `LICENSE` and `.codex/config.toml` document and configure *this* repository; they are not installed anywhere. The operating manual Claude Code follows is inside the engine (`.claude/rules/rnd-manual.md`, loaded automatically), so a host repository keeps its own `CLAUDE.md`.

Paths come from `.claude/rnd-policy.json` → `layout`, which `.claude/scripts/rndlib.py` reads. Moving the data directory is a policy edit; moving `.claude/` itself also needs the hook commands in `.claude/settings.json` updated, because Claude Code resolves those before the policy is read.

Full design: [`SPEC.md`](SPEC.md). Operating manual for Claude Code: [`CLAUDE.md`](CLAUDE.md).

## Requirements
- Python 3.10+ (no third-party packages required; `jsonschema` optional for stricter validation)
- Git, coreutils `timeout`
- `pytest` only to run the engine tests (`pip install pytest`, or `uv run --no-project --with pytest ...`)
- [Claude Code](https://code.claude.com) (project settings in `.claude/`)
- [Codex CLI](https://github.com/openai/codex) on `PATH` (`codex exec` is used for review rounds)

## Use it

### In an existing repository

```bash
git clone https://github.com/nix-tkobayashi/ai-rnd-framework.git        # once, anywhere
python3 ai-rnd-framework/.claude/scripts/rnd.py install /path/to/your-repo
cd /path/to/your-repo
python3 .claude/scripts/rnd.py doctor        # tooling, hooks, schemas, policy - passes with none of our root documents
python3 .claude/scripts/rnd.py new "<title>" --question "<your question>"
```

`install` copies the engine into `.claude/`, creates the `.rnd/` skeleton, merges `.claude/settings.json` if the repository already has one (permission lists are united; engine hooks are appended next to yours) and adds the three generated files to `.gitignore`. It never writes anything else: your `README.md`, `CLAUDE.md`, code, and your own files under `.claude/` stay as they are. It checks before it writes and refuses, without touching the repository, when files already exist at engine paths, when a destination goes through a symlink, or when the existing `settings.json` is not valid JSON. A repository that already has the engine is refused unless you pass `--upgrade`, which replaces the engine files, keeps your merged `settings.json`, and saves a modified `rnd-policy.json` as `rnd-policy.json.orig-<old version>` for you to re-apply local changes (for example a `protectedPaths.builderAllowed` entry that opens part of your code to builders).

Inside a host repository the builders' write boundary covers the host's own code: builders may write only case output (`.rnd/cases/<CASE>/artifacts/`, experiment logs, `/tmp`) unless `.claude/rnd-policy.json` → `protectedPaths.builderAllowed` names another path. The engine's `permissions.deny` (`~/.ssh`, `~/.aws`, `sudo`, `git push --force`, `git reset --hard`) and its `PreToolUse` hooks apply to every session in that repository, not only to R&D work.

### As a dedicated workspace

```bash
git clone https://github.com/nix-tkobayashi/ai-rnd-framework.git my-rnd-workspace
cd my-rnd-workspace && rm -rf .git && git init -b main
python3 .claude/scripts/rnd.py doctor
python3 -m pytest .claude/tests -q           # engine tests
python3 .claude/scripts/rnd.py new "<title>" --question "<your question>"
```

Either way `.rnd/cases/` and `.rnd/knowledge/` start empty on purpose: the framework carries no R&D data, and **your** cases are meant to be tracked in your repository (SPEC 33/45 - the case history and the knowledge are the output). Only the generated index (`.rnd/index.json`, `.rnd/INDEX.md`, `.rnd/knowledge/catalog.json`) stays untracked; `rnd.py doctor` recreates it on a fresh clone.

Upgrading later: pull this repository and run `python3 <clone>/.claude/scripts/rnd.py install <your repo> --upgrade`. The installed version is `.claude/VERSION`.

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

Three mechanisms, with very different strengths. Being precise about them matters more than the
word "secure":

| Mechanism | What it is | What it actually gives you |
|-----------|-----------|----------------------------|
| Codex sandbox | `codex exec -s read-only` | A real sandbox. The reviewer cannot write, whatever it decides to do. |
| Tool-level write guard | the `builder-write-guard` hook on Write / Edit / MultiEdit / NotebookEdit | The write boundary for agent *tool* calls. The path arrives as a structured argument, so there is no shell text to interpret. |
| Bash command filter | the `safety-gate` and `reviewer-shell-guard` hooks | **Advisory.** It rejects some recognisable risky commands to reduce accidental damage. It does not decide whether a shell command is safe. |

The Bash filter is deliberately not a guarantee. It tokenises with `shlex` and blocks what it
recognises, but it **can miss destructive commands and can reject harmless ones**. It is not a
sandbox and not an authorisation boundary. Known limits, so an unexpected denial is recognisable:

- **Misses.** A command built inside an interpreter (`bash -c "..."`, `python3 -c "os.system(...)"`)
  is not analysed as shell. Uncommon spellings of destructive git commands get through
  (`git push origin +HEAD:main`, `git reset HEAD --hard`).
- **False positives.** A protected path or a write verb appearing as an *argument* can trip it:
  `rg touch .claude/scripts`, `cp README.md /tmp/copy`, `git worktree list`. Relative paths are read
  as workspace paths; only `cd <relative dir> &&` earlier in the same command moves them (after
  `cd dir;` or a newline the old directory is checked too, and an absolute `cd` is not followed), so
  chain with `&&` and use an absolute path (`/tmp/...`) for scratch files outside the workspace.

If you need a hard boundary around shell execution, put one outside this framework: run it in a
container or a VM, or use the Claude Code permission settings, which you own. The value of the role
separation here is that the *reviewer* and the *validator* are genuinely independent of the builder,
not that the builder is imprisoned.

## Key guarantees
| Principle | Enforced by |
|-----------|-------------|
| Researcher/Critic and Builder/Reviewer/Validator are different agents | `.claude/agents/*.md`, orchestrator skill |
| Claude-written code is reviewed by Codex; Claude cannot close a finding; every fix goes back to Codex | `.claude/scripts/codex_review.py`, `rnd.py finding set` (Claude may only set `fixed_pending_review` / `disputed`) |
| Convergence rules (0 actionable findings + tests PASS; 2× CLEAN for high risk; maxRounds 5; no forced PASS) | `.claude/scripts/review_gate.py`, `.claude/rnd-policy.json` |
| Oscillation (same finding re-opened) escalates to the Lead | fingerprints + `reopenCount` in `findings.json` |
| Codex runs read-only; agent tool writes are confined to each role's paths | Codex `-s read-only` (a real sandbox) and the tool-level write guard. The Bash filter is advisory - see above |
| Case files are the single source of truth, resumable from any session | `.rnd/cases/<CASE>/case.json`, `rnd.py resume`, `handoff.md` |
| Evidence carries provenance and freshness; stale evidence is flagged | `.claude/schemas/evidence.schema.json`, `rnd.py evidence check` |
| Knowledge is promoted deliberately, never automatically | `.rnd/knowledge/candidates/` → review → `.rnd/knowledge/shared/` |

## Scripts
| Script | Purpose |
|--------|---------|
| `.claude/scripts/rnd.py` | case lifecycle CLI (new/search/resume/state/research/report/agent/evidence/experiment/review/findings/tests/validate/decide/archive/index) and `install <repo> [--upgrade]` |
| `.claude/scripts/codex_review.py` | one Codex review round: tests → `codex exec` (read-only, JSON schema) → merge findings → gate |
| `.claude/scripts/review_gate.py` | convergence verdict: CONVERGED / NOT_CONVERGED / FAILED_TO_CONVERGE / REVIEW_OSCILLATION |
| `.claude/scripts/safety_check.py` | command / path / secret / diff checks shared by the hooks |
| `.claude/scripts/generate_index.py` | regenerates `.rnd/index.json`, `.rnd/INDEX.md`, `.rnd/knowledge/catalog.json` |
| `.claude/scripts/rnd_doctor.py` | health check of tooling, layout, policy, hooks, schemas, cases |
| `.claude/scripts/rndlib.py` | shared helpers (paths, schema validation, state machine, git) |

Version: `python3 .claude/scripts/rnd.py --version`. Engine tests: `python3 -m pytest .claude/tests -q` (or without a system pytest: `uv run --no-project --with pytest -- python -m pytest .claude/tests -q`).

## License

MIT - see [`LICENSE`](LICENSE).
