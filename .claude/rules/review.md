# Review rules (always loaded)

1. **Any code change makes Codex review mandatory.** `rnd.py review init <CASE> --required-test "<cmd>"` then `python3 .claude/scripts/codex_review.py <CASE>` for every round.
2. **Codex is the reviewer, not Claude.** The `codex-reviewer` agent is a wrapper: Claude wrapper → Codex CLI → Codex model. It never edits code (read-only sandbox + shell guard).
3. **Claude cannot close a finding.** Claude may only set `fixed_pending_review` or `disputed` (`rnd.py finding set`). `confirmed_fixed` / `false_positive` are written only by `codex_review.py` from Codex's verdict. `accepted_risk` is a Lead decision and needs a note.
4. **After every fix: tests, then Codex again.** No exceptions for "trivial" fixes. `codex_review.py` runs the required tests before calling Codex so the order is enforced.
5. **Convergence** = actionable findings 0 AND required tests PASS. High-risk cases need 2 consecutive CLEAN rounds. `review_gate.py` decides; humans and Claude do not.
6. **maxRounds = 5.** No convergence by round 5 → `FAILED_TO_CONVERGE`, back to the Lead. Forced PASS is forbidden.
7. **Oscillation** (a finding re-opened twice after fixes) → `REVIEW_OSCILLATION`, case `BLOCKED`, Lead arbitrates before any further round.
8. **Codex CLEAN ≠ done.** The Validator checks behaviour / acceptance criteria / reproducibility separately. The Builder never records the final PASS.
9. **Baseline first.** Builders run the required tests before touching code and record `tests-baseline.json`, so pre-existing failures are not confused with regressions.
10. Codex timeouts: do not retry the identical prompt; narrow with `--paths` or report to the Lead.
