# R&D engine - operating manual (always loaded)

This repository carries the **ai-rnd-framework** engine in `.claude/` and its R&D data in `.rnd/`. It may be a dedicated R&D workspace or any other repository (a product, a service, an infrastructure repository) that runs R&D cases next to its own code. The engine's design is `SPEC.md` in the framework repository; this file is the operating manual for Claude Code. Engine version: `.claude/VERSION`.

## What the engine is
- **R&D Engine**: `.claude/` (agents, skills, hooks, rules, policy, `scripts/`, `schemas/`, `tests/`)
- **Shared Knowledge**: `.rnd/knowledge/shared/` (validated, reusable), `.rnd/knowledge/candidates/` (awaiting review), `.rnd/knowledge/catalog.json`
- **R&D History**: `.rnd/cases/RND-YYYYMMDD-NNN-<slug>/` - one directory per topic (AWS, GPU, LLM, Claude Code, ... are *cases*, never repos)

The main Claude session is the **R&D Lead**. It coordinates subagents and is the only writer of case management files, always through `.claude/scripts/rnd.py`. Requests that are not R&D work (ordinary changes to this repository's own code) do not go through a case.

## Start here (every R&D request)
```bash
python3 .claude/scripts/rnd.py search "<topic>"      # 1. is there a case already?  → resume it
python3 .claude/scripts/rnd.py resume <CASE>         # 2. session-independent status: state, research, experiments, open findings, validation, last/next action
python3 .claude/scripts/rnd.py new "<title>" --type research|experiment|implementation --risk standard|high --tags .. --question ".."   # 3. otherwise
```
Then invoke the `rnd-orchestrator` skill (`/rnd-orchestrator <question>`) to run the workflow, or `rnd-case` for single operations.

## Workflow
`User question → Lead → case search → (resume | create) → Researchers ×≤3 ∥ Critics ×≤2 → synthesis → Experiment Designer → Builder → Codex review ⇄ Claude fix (converge, ≤5 rounds) → Validator → Decision → Archive → knowledge promotion`

## Agents (`.claude/agents/`)
| Agent | Role | Writes |
|-------|------|--------|
| researcher | current primary-source evidence, one angle each | no |
| critic | counter-evidence, independent of researchers | no |
| claim-verifier | re-verify one claim / EV-id | no |
| experiment-designer | hypothesis, procedure, acceptance criteria | no |
| builder / isolated-builder | approved experiments & PoC code; baseline tests first; isolated = own git worktree for A/B/C | `.rnd/cases/<CASE>/artifacts/`, experiment logs only |
| codex-reviewer | wrapper → `codex exec` (read-only sandbox) → findings.json | review round files only (via script) |
| validator | behaviour, acceptance criteria, reproducibility | no (tests only) |

Read-only agents return their report as the final message; the Lead stores it (`rnd.py research add --file` for research/critic reports, `rnd.py report add --file` for builder/validator reports). Builders may write only `.rnd/cases/<CASE>/artifacts/`, `experiments/EXP-*/logs/` and `/tmp` (`protectedPaths.builderAllowed` in `.claude/rnd-policy.json`); everything else, this repository's own code included, is denied unless the policy opens it. `builder-write-guard.py` is the write boundary for tool calls (Write/Edit/MultiEdit/NotebookEdit). `safety-gate.py` and `reviewer-shell-guard.py` filter Bash commands, but they are advisory: they reject recognisable risky commands and can both miss destructive ones and refuse harmless ones.

## Non-negotiables
1. Researcher ≠ Critic. Builder ≠ Reviewer ≠ Validator.
2. Code changed ⇒ Codex review is mandatory: `python3 .claude/scripts/codex_review.py <CASE>`. Claude never closes a Codex finding (`confirmed_fixed`/`false_positive` come only from Codex via the script); after every fix, Codex again.
3. Convergence = actionable findings 0 + required tests PASS (+ 2 consecutive CLEAN when risk=high). `review_gate.py` decides. `maxRounds=5` → `FAILED_TO_CONVERGE`; repeated re-opening → `REVIEW_OSCILLATION`. No forced PASS.
4. `case.json` is the single source of truth; the conversation is not. Priority: case.json > case artifacts > evidence > shared knowledge > conversation.
5. Evidence (with source, retrievedAt, freshnessClass) is separate from interpretation (`synthesis.md`) which is separate from the decision (`decision.md`).
6. Past cases are reused, never trusted blindly: `rnd.py evidence check <CASE>` flags stale items (fast-moving 30d / normal 180d / stable 365d).
7. Agents hold *how to work*; cases hold *what is true*. No per-agent knowledge memory.
8. Builders cannot modify `.claude/`, `.rnd/knowledge/`, case management files, or this repository's own code outside `protectedPaths.builderAllowed`.
9. Never split the R&D data by topic into other repositories. Worktrees are for parallel alternatives inside a case only.

## Commands
| Task | Command |
|------|---------|
| Health check | `python3 .claude/scripts/rnd.py doctor` |
| Case ops | `python3 .claude/scripts/rnd.py {new,search,list,show,resume,state,next,action,research,report,agent,evidence,experiment,review,findings,finding,tests,validate,decide,archive,handoff,stale,index,brief}` |
| Agent timeline (wall-clock audit) | `python3 .claude/scripts/rnd.py agent start <CASE> <agent> "<task>"` / `agent done <CASE> <agent>` / `agent status <CASE>` |
| Codex round | `python3 .claude/scripts/codex_review.py <CASE> [--diff-base REF] [--paths ..] [--focus ..] [--dry-run]` |
| Gate | `python3 .claude/scripts/review_gate.py <CASE> [--json]` |
| Safety | `python3 .claude/scripts/safety_check.py {command,path,secrets,diff} ...` |
| Index | `python3 .claude/scripts/generate_index.py [--check]` |
| Engine upgrade | from a clone of ai-rnd-framework: `python3 .claude/scripts/rnd.py install <this repo> --upgrade` |
| Tests for the engine itself | `python3 -m pytest .claude/tests -q` (no system pytest? `uv run --no-project --with pytest -- python -m pytest .claude/tests -q`) |

## Conventions
- Layout: the engine is `.claude/` (`scripts/ schemas/ tests/ pytest.ini VERSION rnd-policy.json` alongside `agents/ skills/ hooks/ rules/`), the data is `.rnd/` (`cases/ knowledge/ index.json INDEX.md`). Paths come from `.claude/rnd-policy.json` -> `layout`; change them there, never hard-code.
- Case id `RND-YYYYMMDD-NNN`; directory `.rnd/cases/<id>-<slug>/`. Never edit `.rnd/index.json`, `.rnd/INDEX.md`, `.rnd/knowledge/catalog.json`, `handoff.md` by hand.
- Commit case directories as phases complete; no attribution lines in commit messages. Scan with `python3 .claude/scripts/safety_check.py diff` before committing.
- Codex CLI: never pin `-m`; the wrapper adds `--skip-git-repo-check -s read-only --output-schema` and a `timeout`. On timeout do not retry the identical prompt.
- Python 3.10+ only, no third-party dependencies (`jsonschema` is optional).
- Fix rounds in the Codex loop run required tests only; the Validator re-measures experiments after convergence. Keep agent reports within the word caps in their definitions.
- The Bash filter tokenises with `shlex`, ignores heredoc *data* and reads relative paths as workspace paths (it does not model `cd`), so use absolute paths for scratch files outside the workspace. It is advisory, not a boundary: see the framework README for its known misses and false positives.
- Local notes go in `CLAUDE.local.md` (git-ignored).
