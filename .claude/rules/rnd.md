# R&D workspace rules (always loaded)

1. **One repository, many cases.** R&D cases live in this repository's `.rnd/cases/RND-YYYYMMDD-NNN-<slug>/`, whether it is a dedicated workspace or a product repository carrying the engine. Never propose a new repo or workspace for a new topic: different topic = different case.
2. **Search before creating.** Every R&D request (a question to investigate, an experiment, a PoC) starts with `python3 .claude/scripts/rnd.py search "<topic>"`. Resume an existing case when the topic matches; otherwise `rnd.py new`. Ordinary work on this repository's own code is not a case.
3. **`case.json` is the truth.** Case state, findings, validation and decision live in files under `.rnd/cases/<CASE>/`. The conversation is not the record. Priority: `case.json` > case artifacts > evidence > `.rnd/knowledge/shared/` > conversation.
4. **Only the Lead writes management files**, and only via `.claude/scripts/rnd.py`. Subagents return reports as their final message; the Lead persists them (`rnd.py research add --file`).
5. **Researcher ≠ Critic, Builder ≠ Reviewer, Builder ≠ Validator.** Do not let one agent play two of these roles in a case.
6. **Evidence ≠ interpretation.** `evidence.json` holds claims with provenance (source, retrievedAt, freshnessClass). Interpretation goes in `synthesis.md`. Decisions go in `decision.md`.
7. **Old cases are hints, not facts.** Evidence past its freshness window (`rnd.py evidence check`) must be re-verified against primary sources before it is relied on.
8. **Concurrency:** at most 6 agents in flight; Researcher ×3, Critic ×2. Parallel builders (alternatives) use git worktrees inside this repo, never separate workspaces.
9. **Freshness class** `fast-moving` for Claude Code, Codex, AWS features, LLM runtimes, Kubernetes releases, GPU stacks.
10. **Never edit `.rnd/index.json` / `INDEX.md` / `.rnd/knowledge/catalog.json` by hand** - `rnd.py index` regenerates them.
11. Keep technical facts in the case, not in agent memory. Agents define *how to work*, cases hold *what is true now*.
\n12. **Output language follows the case** (`case.json → language`, detected from the question, `--lang` to override). Sources are read in their own language; reports, synthesis, decision, plans and Codex finding texts are written in the case language; quotes, code, commands, identifiers and enum values are never translated.\n
13. **The Bash filter is advisory.** It blocks recognisable risky commands but is not a sandbox or an authorisation boundary; it can miss destructive commands and refuse harmless ones. Tool-call writes are the boundary that holds.
