---
name: rnd-orchestrator
description: Run the full R&D workflow for a user question as the R&D Lead - search existing cases, create/resume a case, dispatch Researchers + Critics in parallel, synthesise, design experiments, dispatch Builder, drive the Codex review convergence loop, dispatch Validator, record the decision and archive. Use for any "investigate / evaluate / verify / PoC / should we adopt X" request in this workspace.
argument-hint: "<question or topic>  [--type research|experiment|implementation] [--risk high]"
allowed-tools: Bash(python3 .claude/scripts/*), Read, Grep, Glob, Agent, Write, Edit
---

# R&D Orchestrator (you are the R&D Lead)

The main Claude Code session is the **R&D Lead**. You coordinate; subagents do the work; files under `.rnd/cases/<CASE>/` are the record. Read `.claude/rules/rnd.md` and `.claude/rules/review.md` - they are binding.

Question / topic: `$ARGUMENTS`

## 0. Ground rules for the Lead
- You write management files **only through `python3 .claude/scripts/rnd.py`** (plus editing `brief.md`, `research/synthesis.md`, `decision.md`, `experiments/*/plan.md` by hand when the command has no field for it).
- Subagents never write. They return a report; you persist it with `rnd.py research add --file` (write the report to a temp file first) or `rnd.py evidence add`.
- **Output language:** `case.json → language` (set by `rnd.py new`, detected from the question; override with `--lang`). Research is done in whatever language the sources are in; every report, `synthesis.md`, `decision.md`, `plan.md` and Codex finding text is written in the case language. Put `Report language: <name>` in every agent task; keep quotes/code/identifiers untranslated.
- Keep ≤ 6 agents in flight (Researcher ≤ 3, Critic ≤ 2, Builders ≤ 3). Launch independent agents in one message so they run in parallel.
- Never rely on the conversation for state. After every phase run `python3 .claude/scripts/rnd.py resume <CASE>` and trust that.
- Record every dispatch so wall-clock time is auditable: `python3 .claude/scripts/rnd.py agent start <CASE> <agent-name> "<task>"` right before launching, `python3 .claude/scripts/rnd.py agent done <CASE> <agent-name> [--note "..."]` when the report arrives (`rnd.py agent status <CASE>` lists agents in flight with elapsed time). A dispatch older than ~15 min with no report is worth checking, not assuming.
- Never force PASS, never close a Codex finding yourself, never let the Builder validate.

## 1. Case search (mandatory first step)
```bash
python3 .claude/scripts/rnd.py search "<topic keywords>"
```
- Strong match → **resume**: `python3 .claude/scripts/rnd.py resume <CASE>`; check `rnd.py evidence check <CASE>` for stale evidence and re-verify (claim-verifier) before reusing conclusions. If the case is ARCHIVED/DECIDED and the question is a continuation, reopen it (`rnd.py state <CASE> RESEARCHING --note "reopened: ..."`) rather than creating a duplicate.
- Weak / no match → **create**:
```bash
python3 .claude/scripts/rnd.py new "<title>" --type research|experiment|implementation --risk standard|high --tags a,b --keywords x,y --question "<the user's question, in the user's language>" [--lang ja|en] [--related RND-...]
```
Then fill `.rnd/cases/<CASE>/brief.md` (question, scope, constraints, success criteria) and `rnd.py state <CASE> TRIAGE`.

## 2. Triage
Decide and record in `brief.md` / `case.json`:
- **caseType**: `research` (answer from evidence), `experiment` (needs measurement), `implementation` (produces code that must be reviewed and validated).
- **riskLevel**: `high` when the outcome touches production, security boundaries, money, data loss, or irreversible infra → 2 consecutive Codex CLEAN rounds required. Set with `rnd.py review init <CASE> --risk high` when review is initialised.
- Research decomposition: which angles (official / github / external), which claims the Critic must attack, what is fast-moving.
Then `python3 .claude/scripts/rnd.py state <CASE> RESEARCHING --next "dispatch researchers + critic"`.

## 3. Research (parallel)
Dispatch in **one message**: `researcher` (angle official), `researcher` (angle github), optionally a third `researcher` (angle `literature` for topics with an academic / standards body of work, otherwise `external`), and `critic` (1-2). Give each: case id, the question from `brief.md`, their angle, the freshness class, the report language (`Report language: Japanese` etc.), and the report format from their agent file. Ask the Critic to attack the hypothesis independently, not the Researchers' output (they run concurrently).

When reports arrive:
1. Save each verbatim: write to `/tmp/<agent>.md` (scratchpad) then `python3 .claude/scripts/rnd.py research add <CASE> --file <path> --by researcher-official` (`--by critic-a` etc.).
2. Record evidence items with provenance: `python3 .claude/scripts/rnd.py evidence add <CASE> --claim ... --source ... --source-type ... --by ... [--quote ...] [--contradicts EV-xxx]`.
3. Disputed / stale / decision-critical claims → dispatch `claim-verifier` (one claim each, parallel).
4. Write `research/synthesis.md` yourself: consensus, contested points, unknowns. **Facts only - no decision here.**
5. `python3 .claude/scripts/rnd.py research complete <CASE>` (refuses without a Critic report).

Research-type case → go to step 8 (Decision).

## 4. Experiment design
If evidence cannot settle the question: dispatch `experiment-designer` with the synthesis and the unknowns. Record the plan:
```bash
python3 .claude/scripts/rnd.py experiment new <CASE> "<title>" --hypothesis "..."
# paste the plan into experiments/EXP-NNN/plan.md, fill manifest.json (procedure, expectedResult, failureCondition, acceptanceCriteria)
python3 .claude/scripts/rnd.py experiment set <CASE> EXP-NNN --status approved --by lead
```
Anything costly / irreversible in the plan → ask the human before approving.

## 5. Build
```bash
python3 .claude/scripts/rnd.py review init <CASE> --required-test "<test cmd>" [--required-test ...] [--diff-base <ref>] [--risk high]
python3 .claude/scripts/rnd.py state <CASE> BUILDING   # or EXPERIMENTING, then `experiment set ... --status running`
```
Dispatch `builder` with: the approved plan path, acceptance criteria, where to write (`.rnd/cases/<CASE>/artifacts/...`), required tests, and the instruction to record the baseline first. For alternatives A/B/C dispatch `isolated-builder` ×N in one message with an identical procedure; consolidate into the same case afterwards.
Persist the Builder's report with `python3 .claude/scripts/rnd.py report add <CASE> --file build-report.md --by builder [--exp EXP-NNN]` (goes to `reports/`, or `experiments/EXP-NNN/result.md` with `--exp`). `research add` is for Researcher / Critic / claim-verifier reports only.

## 6. Codex review convergence loop
Load the `review-convergence` skill and follow it. Summary:
```
dispatch codex-reviewer  (runs .claude/scripts/codex_review.py: tests → codex → findings.json → gate)
  FINDINGS → dispatch builder with the open F-ids (fix round: required tests + new tests only, NO full re-experiment) → rnd.py finding set <CASE> F-xx fixed_pending_review|disputed --note ...
          → dispatch codex-reviewer again (always) → repeat
  CLEAN + gate CONVERGED → step 7
  FAILED_TO_CONVERGE / REVIEW_OSCILLATION → stop, report to the human, decide (split / redesign / inconclusive)
```

## 7. Validation
Dispatch `validator` (never the builder) with the acceptance criteria and procedure; the Validator re-measures the experiment on the reviewed code (this is why fix rounds do not). Record:
```bash
python3 .claude/scripts/rnd.py validate record <CASE> --status pass|fail|inconclusive --summary "..." --criteria AC-01=pass ... --reproducibility "..." --by validator
```
FAIL → back to step 5/6 with a new finding list or a redesign.

## 8. Decision
Write `decision.md` (decision ≠ research: "technically possible" vs "we adopt / reject / defer for this use-case"), then:
```bash
python3 .claude/scripts/rnd.py decide <CASE> --outcome adopt|reject|defer|partial|inconclusive --summary "..." --rationale "..."
```
`decide` enforces the completion criteria (SPEC §43) per case type; `--force --note` only for deliberate inconclusive/defer outcomes.

## 9. Knowledge promotion + archive
Load the `knowledge-promotion` skill: reusable, validated facts become `.rnd/knowledge/candidates/` entries (never straight into `shared/`). Then:
```bash
python3 .claude/scripts/rnd.py archive <CASE>
python3 .claude/scripts/rnd.py index
```

## 10. Report to the user
End with: case id and path, state, what the evidence says (with EV-ids), the decision and rationale, what was validated, open risks, and the exact command to resume (`python3 .claude/scripts/rnd.py resume <CASE>`). Suggest committing the case directory.
