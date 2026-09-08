# Changelog

All notable changes to the ai-rnd-workspace engine are recorded here. The engine
version lives in `VERSION` (semantic versioning); R&D cases under `.rnd/cases/`
are history, not part of the engine version.

The published history starts at 0.5.0, the first release meant to be shared.
Versions 0.1.0-0.4.0 were developed privately and their commits are not part of
this repository; the entries below record what changed in each of them.

## [0.6.0] - 2026-09-08

Fixes for the blockers found by an independent Codex audit of the 0.5.0 tree.

### Fixed - completion and convergence guarantees
- `rnd.py state` can no longer reach `DECIDED` or `ARCHIVED`. Those states carry the completion
  criteria, so they are reachable only through `decide` / `archive`, which check them. Previously
  `state <CASE> DECIDED` followed by `archive` produced an archived case with
  `decision.status=pending` and no research done.
- `archive` requires a recorded decision, not just the `DECIDED` state.
- `decide --force` is restricted to the `defer` / `inconclusive` outcomes it was documented for;
  `adopt` / `reject` / `partial` require the completion criteria to be met.
- The review gate always requires the configured number of consecutive CLEAN rounds from Codex.
  Clearing the last finding by another route (`accepted_risk`, `false_positive`) no longer
  converges a case that never had a CLEAN round.
- An ERROR round resets `consecutiveClean`, so CLEAN then ERROR then CLEAN no longer counts as two
  consecutive clean rounds for a high-risk case.
- A finding re-reported at a higher severity regains `actionable`, so an item first filed as `info`
  cannot stay invisible to the gate.
- `rnd.py review reopen <CASE> --note ...` clears a `REVIEW_OSCILLATION` / `FAILED_TO_CONVERGE`
  status after Lead arbitration. The documented recovery previously left the case unable to run
  another round.
- `codex_review.py` takes the reviewed file list from `git diff --name-only -z` instead of parsing
  `diff --git` headers, which raised `IndexError` on quoted or non-ASCII filenames.

### Fixed - guardrails
- Heredoc bodies: an unquoted delimiter expands command substitutions, and a body piped into an
  interpreter runs. Both are now scanned; only inert data bodies are skipped.
- Command substitution inside double quotes is scanned instead of being stripped with the quotes.
- `write_targets` follows `cd`, removes shell quoting, and recognises interpreter one-liner writes,
  so a builder cannot leave its write boundary by those routes.
- Blocked patterns now catch `rm` with its flags written separately, quoted targets, and the
  `git -C <dir>` / `git -c key=value` spellings of the destructive git commands;
  `git update-ref -d` was added.
- Read-only agents: newlines separate commands, option-style denials match `--output=file`,
  `find` with `-delete` / `-exec` is denied, and `curl` is no longer on the validator profile.
- Inline `python3 -c` for the validator is judged on module and method use, so aliasing an import
  no longer bypasses it.

### Changed
- README says plainly what the hooks are: defence in depth, not a sandbox. Codex's `-s read-only`
  is the one real sandbox in the loop.
- The `layout` policy claim is qualified: moving `.claude/` also needs the hook commands in
  `settings.json` edited, because Claude Code resolves those before the policy is read.
- `pytest` is listed as a requirement for running the engine tests.
- Stale pre-0.4.0 paths removed from the schemas, `.codex/config.toml` and `.rnd/knowledge/README.md`.

## [0.5.0] - 2026-09-08

### Fixed
- `slugify` keeps non-ASCII letters, so Japanese/Korean/Chinese case titles no longer collapse to the directory name `RND-YYYYMMDD-NNN-case`; the `slug` schema pattern was relaxed accordingly.
- An engine version bump no longer makes `generate_index.py --check` (and therefore `rnd_doctor.py`) report the index as stale.

### Changed
- The repository is now a **distributable framework**: it ships the engine and documentation with no R&D data. The dry-run case and its knowledge candidate are no longer part of the repository; `.rnd/cases/` and `.rnd/knowledge/{shared,candidates}/` ship empty with `.gitkeep`.
- Generated files are no longer tracked: `.rnd/index.json`, `.rnd/INDEX.md`, `.rnd/knowledge/catalog.json`. `rnd_doctor.py` regenerates them when missing instead of failing, so a fresh clone passes the health check.
- README: "Use it as your own workspace" section (copy, doctor, tests, first case). Users' own cases are still meant to be committed in their copy (SPEC 33/45).
- Engine tests build a fresh `.rnd` skeleton instead of copying local R&D data, so the suite no longer depends on - or duplicates - case files.

## [0.4.0] - 2026-09-08

### Changed (breaking: paths)
- Everything except the top-level documents now lives in dot-directories. `scripts/`, `schemas/`, `tests/`, `pytest.ini` moved into `.claude/`; `rnd/` and `knowledge/` moved into `.rnd/` as `.rnd/cases/` and `.rnd/knowledge/`; the index is `.rnd/index.json` / `.rnd/INDEX.md`. Only `README.md`, `SPEC.md`, `CLAUDE.md`, `CHANGELOG.md` and `VERSION` remain visible at the root. Case history was moved with `git mv`, so per-file history is preserved.
- Commands change accordingly: `python3 .claude/scripts/rnd.py ...`, `python3 -m pytest .claude/tests -q`.
- New `layout` section in `.claude/rnd-policy.json` (`engineDir`, `scriptsDir`, `schemasDir`, `testsDir`, `dataDir`, `casesDir`, `knowledgeDir`); `rndlib` reads it, so a future move is a one-place change.
- Builder-protected paths are now `.claude/`, `.codex/`, `.rnd/`, `.git/` and the top-level documents; the writable exceptions are `.rnd/cases/RND-*/artifacts/` and `.rnd/cases/RND-*/experiments/EXP-*/logs/` (plus `/tmp`).
- `.gitignore` documents how to ignore the workspace (`.rnd/` for data only, `.claude/ .codex/ .rnd/` for everything).

## [0.3.1] - 2026-09-08

### Fixed
- `VERSION` in v0.3.0 contained a literal `\n`; `rnd_doctor.py` now requires a bare semver line.

## [0.3.0] - 2026-09-08

### Added
- Per-case output language: `case.json → language` (ISO 639-1), detected from the question by `rnd.py new` or set with `--lang`. Research is still done in the sources' languages; reports, `synthesis.md`, `decision.md`, `plan.md` and Codex finding texts are written in the case language; quotes, code, commands, identifiers and enum values stay untranslated.
- Japanese templates for brief / synthesis / sources / decision / plan (English remains the fallback); templates now carry language-neutral markers so `rnd.py decide` works in any language.
- Language rule in all agent definitions, orchestrator / rnd-case / review-convergence skills and `.claude/rules/rnd.md`.
- `codex_review.py` asks Codex to write summary / title / description / suggestedFix / comment in the case language.

### Fixed
- Finding fingerprints are unicode-aware; non-ASCII titles no longer collapse to the same fingerprint (which would have caused false REVIEW_OSCILLATION).

## [0.2.1] - 2026-09-08

### Fixed
- `rnd.py`: every mutating command now regenerates `rnd/index.json`, `rnd/INDEX.md` and `knowledge/catalog.json`, so `rnd_doctor.py` no longer warns "index out of date" after routine case updates (0.2.0 shipped with one failing engine test for this reason).

## [0.2.0] - 2026-09-08

### Added
- `researcher` angle `literature` (peer-reviewed papers, preprints, standards): canonical-version rule, measured-claim-with-conditions rule, stable vs fast-moving split for "state of the art" claims, secondary citations start at low confidence.
- Evidence schema fields for literature: `doi`, `venue`, `peerReviewed`, `artifactsAvailable`, `reproducedBy`, `conditions`; `rnd.py evidence add --doi --venue --peer-reviewed --artifacts --reproduced-by --conditions`.
- Critic instruction to attack paper-derived claims on reproducibility and conditions.
- Orchestrator dispatches a `literature` researcher for topics with an academic / standards body of work.

## [0.1.0] - 2026-09-08

Initial release, built from `SPEC.md` v1.1.

### Engine
- Claude Code project layout: 8 agents (`researcher`, `critic`, `claim-verifier`, `experiment-designer`, `builder`, `isolated-builder`, `codex-reviewer`, `validator`), 4 skills (`rnd-orchestrator`, `rnd-case`, `review-convergence`, `knowledge-promotion`), 3 PreToolUse hooks (`safety-gate`, `builder-write-guard`, `reviewer-shell-guard`), rules, `rnd-policy.json`.
- `scripts/rnd.py`: case lifecycle CLI (search / new / resume / state / research / report / agent timeline / evidence / experiment / review / findings / tests / validate / decide / archive / stale / index / brief / doctor).
- `scripts/codex_review.py`: one independent Codex CLI review round (tests → `codex exec` read-only with JSON output schema → finding merge with fingerprints / reopen counts → convergence gate). Claude can only set `fixed_pending_review` / `disputed`; `confirmed_fixed` / `false_positive` come from Codex.
- `scripts/review_gate.py`: CONVERGED / NOT_CONVERGED / FAILED_TO_CONVERGE (maxRounds 5) / REVIEW_OSCILLATION; 2 consecutive CLEAN rounds for high-risk cases.
- `scripts/safety_check.py`: heredoc-aware command gate, write-target based builder boundary (artifacts/, experiment logs/, /tmp), read-only / test-only shell allow-lists, secret scan, diff scan.
- `scripts/generate_index.py`, `scripts/rnd_doctor.py`, `scripts/rndlib.py`; JSON schemas for case, evidence, findings, experiment manifest, Codex output.
- Engine tests: `.claude/tests/test_engine.py` (stubbed Codex).

### R&D history
- The engine was validated by running one complete case end to end (35 evidence items, a 14-criterion experiment, Codex review converged at round 3/5, validator PASS, a recorded decision). That case is not part of this repository.

### Known limitations
- Semantic search is not implemented (title / tags / keywords / full-text only, per SPEC §41).
- `claim-verifier` and `isolated-builder` have unit-test coverage only; not yet exercised in a real case.
- Windows is out of scope for the hooks and the Codex wrapper.
