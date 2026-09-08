---
name: rnd-case
description: Manage a single R&D case's lifecycle without running the whole workflow - search, create, resume, inspect, change state, record research/evidence/experiments/validation/decision, archive, and reindex via .claude/scripts/rnd.py. Use when the user says "resume case X", "what's the status of ...", "create a case for ...", "record this evidence", "mark the decision", or "archive".
argument-hint: "<search|new|resume|show|state|evidence|experiment|validate|decide|archive|index> [args]"
allowed-tools: Bash(python3 .claude/scripts/*), Read, Grep, Glob, Edit, Write
---

# R&D Case operations

`python3 .claude/scripts/rnd.py` is the only sanctioned way to change case management files. Request: `$ARGUMENTS`

## Quick map
| Need | Command |
|------|---------|
| Is there already a case? | `python3 .claude/scripts/rnd.py search "<words>"` |
| New case | `python3 .claude/scripts/rnd.py new "<title>" --type research\|experiment\|implementation --risk standard\|high --tags .. --keywords .. --question ".." [--lang ja\|en]` (output language is detected from the question; templates and agent reports follow it) |
| Resume in a fresh session | `python3 .claude/scripts/rnd.py resume <CASE>` (Current State / Research Summary / Experiment Status / Open Codex Findings / Validation / Last Action / Next Action) |
| Full record | `python3 .claude/scripts/rnd.py show <CASE>` (case.json) |
| Change state | `python3 .claude/scripts/rnd.py state <CASE> <STATE> [--note ..] [--next ".."] [--force]` |
| Log what happened / what is next | `python3 .claude/scripts/rnd.py action <CASE> ".."` / `python3 .claude/scripts/rnd.py next <CASE> ".."` |
| Store a research report | `python3 .claude/scripts/rnd.py research add <CASE> --file <md> --by researcher-official\|critic-a\|claim-verifier` |
| Store a build / validation / review report | `python3 .claude/scripts/rnd.py report add <CASE> --file <md> --by builder\|validator [--exp EXP-001]` |
| Agent timeline (who is running, how long) | `python3 .claude/scripts/rnd.py agent start <CASE> <agent> "<task>"` / `agent done <CASE> <agent> [--note ..]` / `agent status <CASE>` |
| Evidence with provenance | `python3 .claude/scripts/rnd.py evidence add <CASE> --claim .. --source .. --source-type .. --by .. [--quote ..] [--confidence ..] [--supports/--contradicts EV-xxx]` (papers: `--doi --venue --peer-reviewed --artifacts --reproduced-by --conditions`) |
| Freshness audit | `python3 .claude/scripts/rnd.py evidence check <CASE>` |
| Experiments | `python3 .claude/scripts/rnd.py experiment new <CASE> "<title>" --hypothesis ..` then `experiment set <CASE> EXP-001 --status approved\|running\|passed\|failed\|inconclusive` |
| Review setup / status | `python3 .claude/scripts/rnd.py review init <CASE> --required-test ".." [--diff-base REF] [--risk high]` / `review status <CASE>` |
| Findings | `python3 .claude/scripts/rnd.py findings <CASE> [--all]`, `finding set <CASE> F-01-001 fixed_pending_review\|disputed --note ".."` |
| Tests | `python3 .claude/scripts/rnd.py tests run <CASE> --label baseline\|after\|validation` |
| Validation | `python3 .claude/scripts/rnd.py validate record <CASE> --status pass\|fail\|inconclusive --summary .. --criteria AC-01=pass --by validator` |
| Decision | `python3 .claude/scripts/rnd.py decide <CASE> --outcome adopt\|reject\|defer\|partial\|inconclusive --summary .. [--rationale ..]` |
| Archive / index / stale | `python3 .claude/scripts/rnd.py archive <CASE>` / `index` / `stale [--apply]` |
| Health | `python3 .claude/scripts/rnd.py doctor` |

## States
`NEW → TRIAGE → RESEARCHING → DESIGNING → EXPERIMENTING → BUILDING → REVIEWING → VALIDATING → DECIDED → ARCHIVED`
Exceptions: `BLOCKED`, `FAILED`, `FAILED_TO_CONVERGE`, `INCONCLUSIVE`, `STALE`. Illegal jumps need `--force --note`.

## Case layout (what each file is for)
```
.rnd/cases/RND-YYYYMMDD-NNN-<slug>/
  case.json            SSOT: state, type, risk, review/validation/decision status, history, nextAction
  brief.md             question, scope, constraints, success criteria (Lead edits)
  handoff.md           auto-generated resume summary (never hand-edit; `rnd.py handoff`)
  research/            synthesis.md (facts, Lead writes) · evidence.json (provenance ledger) · sources.md · researcher/critic reports
  reports/             builder / validator / other non-research reports (rnd.py report add)
  experiments/EXP-NNN/ plan.md · manifest.json · result.md · logs/
  reviews/round-NN/    prompt.md · diff.patch · tests.json · codex_output.md · findings.json · meta.json
  validation/          result.json · result.md · tests-*.json
  artifacts/           PoC code AND runnable experiment scripts (the only case paths a Builder may write, besides experiment logs; /tmp is also allowed)
  decision.md          the decision for this use-case (≠ research)
```

## Rules of thumb
- Resume, don't duplicate: same topic → same case, even months later (reopen with `state ... RESEARCHING --note "reopened"`).
- The decision record is separate from the research record; keep "possible" and "we will" apart.
- After manual edits to `brief.md` / `synthesis.md` / `decision.md`, log them: `rnd.py action <CASE> "updated synthesis with ..."`.
- Commit the case directory when a phase completes (the Lead asks the human or commits if instructed). Never commit secrets; `python3 .claude/scripts/safety_check.py diff` scans added lines.
