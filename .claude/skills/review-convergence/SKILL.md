---
name: review-convergence
description: Drive the Codex review convergence loop for an R&D case - Builder change → tests → Codex review → Claude fix → tests → Codex re-review, until actionable findings are zero and required tests pass (2 consecutive CLEAN for high risk), with maxRounds=5, oscillation detection and no forced PASS. Use after any code change in a case, and whenever the user asks to "get this reviewed by Codex" or "converge the review".
argument-hint: "<CASE> [--diff-base REF] [--paths ...] [--focus ...]"
allowed-tools: Bash(python3 .claude/scripts/*), Bash(git diff:*), Bash(git log:*), Bash(git status:*), Read, Grep, Glob, Agent
---

# Codex Review Convergence Loop

Case / options: `$ARGUMENTS`

```
Builder ──► Tests ──► Codex ──► findings?
                                 │ yes                     │ no
                                 ▼                         ▼
                            Claude fix                 gate CONVERGED?
                                 │                         │
                              Tests                        ▼
                                 │                     Validator
                                 └────────► Codex ◄────────┘ (high risk: 2nd CLEAN)
```

## Preconditions
1. `python3 .claude/scripts/rnd.py resume <CASE>` - state is BUILDING/REVIEWING, `review.required=true`.
2. Required tests configured: `python3 .claude/scripts/rnd.py review init <CASE> --required-test "<cmd>" [--diff-base <ref>] [--risk high]`.
3. The Builder has reported baseline (before) and after test results.

## One round
Dispatch the **`codex-reviewer`** agent (or run it yourself when no agent is available). Free text for `--focus` should avoid shell operators outside quotes; inside quotes anything is fine.
```bash
python3 .claude/scripts/codex_review.py <CASE> [--diff-base <ref>] [--paths <files>] [--focus "<what to look at>"]
```
The script: runs required tests → sends diff + pending findings to `codex exec` (read-only sandbox, strict JSON schema; finding texts requested in the case language) → merges with the previous round → writes `reviews/round-NN/` → updates `case.json` → applies the gate.

Exit codes: `0` CLEAN & converged · `2` findings / not converged · `3` FAILED_TO_CONVERGE or REVIEW_OSCILLATION · `4` Codex error (timeout → do **not** rerun the same prompt; narrow with `--paths` or split the change).

## When findings come back
1. `python3 .claude/scripts/rnd.py findings <CASE>` - list open ids.
2. Dispatch **`builder`** with the ids + descriptions. Builder fixes, runs the **required tests and the tests it adds** (not the full experiment - the Validator re-measures after convergence), reports per id. Record the dispatch with `rnd.py agent start/done`.
3. Record Builder's disposition - Claude may only set these two:
   ```bash
   python3 .claude/scripts/rnd.py finding set <CASE> F-01-002 fixed_pending_review --note "guarded nil deref in parse()"
   python3 .claude/scripts/rnd.py finding set <CASE> F-01-003 disputed --note "the file is generated; reviewer's assumption is wrong because ..."
   ```
   `confirmed_fixed` / `false_positive` are **only** written by `codex_review.py` from Codex's verdict. `accepted_risk` is a Lead decision (`--by lead --note`), used sparingly and visible in the record.
4. **Always** run the next Codex round - even for a one-line fix. Codex judges every pending item (`previousFindingsResolution`).

## Stop conditions (from `review_gate.py`, never by hand)
| Gate | Meaning | What the Lead does |
|------|---------|--------------------|
| `CONVERGED` | actionable findings 0, required tests PASS, clean rounds ≥ required (1 standard / 2 high) | dispatch Validator |
| `NOT_CONVERGED` | unresolved / tests failing / need another CLEAN | next fix + round |
| `FAILED_TO_CONVERGE` | round 5 reached | stop; report to the human. Options: split the change, redesign, or record `decide --outcome inconclusive --force --note`. To continue after arbitration use `rnd.py review reopen <CASE> --note "..." [--max-rounds N]`; round numbers only move forward, so earlier rounds stay intact. |
| `REVIEW_OSCILLATION` | a finding re-opened ≥ 2 times (A → fix → B → fix → A) | case is BLOCKED; Lead arbitrates: pick a design, document it in `decision.md`, set the losing finding `accepted_risk --by lead --note` or redesign; then **`python3 .claude/scripts/rnd.py review reopen <CASE> --note "<what you arbitrated>"`** (this is the only thing that clears the blocking status and returns the case to BUILDING) and continue. Note that a case cleared this way still needs a real CLEAN round from Codex to converge. |

Forced PASS, editing `findings.json` by hand, or deleting a round directory are prohibited. If Codex is unavailable, the case stays in REVIEWING; it does not proceed to validation.

## Report to the Lead / user after each round
Round number, verdict, tests, findings with ids and status, gate verdict, and the next action. Paths: `.rnd/cases/<CASE>/reviews/round-NN/`.
