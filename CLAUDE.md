# ai-rnd-framework

This repository is the **distribution** of the R&D engine: `.claude/` (the engine) plus its documentation. The operating manual Claude Code follows in any repository that carries the engine is `.claude/rules/rnd-manual.md`; the principles are `.claude/rules/rnd.md` and `.claude/rules/review.md`. They are loaded here too, so this clone also works as a plain R&D workspace: `.rnd/cases/` and `.rnd/knowledge/` start empty and are meant to be committed in your copy.

Other repositories get the engine with `python3 .claude/scripts/rnd.py install <repo>` (and `--upgrade` later); see README.

## Working on the engine itself
- Engine version is `.claude/VERSION` (semver) + `CHANGELOG.md`; bump both and tag `vX.Y.Z` when anything under `.claude/` changes behaviour. Cases under `.rnd/cases/` are history and do not bump the version.
- Only `README.md`, `SPEC.md`, `CLAUDE.md`, `CHANGELOG.md`, `LICENSE` sit at the repository root; they document the framework and are not installed into other repositories. `.codex/config.toml` is this repository's own Codex CLI settings, also not installed.
- Everything a host repository needs must live under `.claude/` (`rndlib.ENGINE_ITEMS`) or be created by `rnd.py install`. `rnd_doctor.py` must pass in a host that has none of the root documents.
- Tests: `python3 -m pytest .claude/tests -q`. They run on a throw-away copy of `.claude/` only.
- Python 3.10+, no third-party dependencies (`jsonschema` optional). No attribution lines in commit messages.
