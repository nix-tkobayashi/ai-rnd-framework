---
name: knowledge-promotion
description: Promote validated, reusable findings from an R&D case into workspace knowledge - first as a candidate under .rnd/knowledge/candidates/, then (after review) into .rnd/knowledge/shared/ with provenance and freshness metadata. Use at case archive time or when the user says "save this as shared knowledge". Never copies raw research or unvalidated claims into shared knowledge.
argument-hint: "<CASE> [--promote <candidate-file>]"
allowed-tools: Bash(python3 .claude/scripts/*), Read, Grep, Glob, Write, Edit
---

# Knowledge Promotion

Case / candidate: `$ARGUMENTS`

```
Case finding ─► Validated? ─► Reusable beyond this case? ─► .rnd/knowledge/candidates/<slug>.md ─► Review ─► .rnd/knowledge/shared/<slug>.md
```
Priority when agents look things up: **Case knowledge > Shared workspace knowledge > Agent memory.** Shared knowledge is a pointer to validated case evidence, not a replacement for it.

## Step 1 - Select candidates (Lead)
From `.rnd/cases/<CASE>/` (`decision.md`, `validation/result.md`, `research/synthesis.md`), pick items that are:
- **Validated** (experiment passed / validator PASS / verified primary source), not merely researched;
- **Reusable** across future cases (a limit, a pattern, a gotcha, a working procedure), not a one-off decision;
- **Attributable** to evidence ids (`EV-xxx`) or experiment ids (`EXP-NNN`).
Decisions specific to one use-case stay in the case. Raw vendor docs are never copied - link them.

## Step 2 - Write the candidate
Create `.rnd/knowledge/candidates/<slug>.md` with this frontmatter (parsed by `generate_index.py` into `.rnd/knowledge/catalog.json`):
```markdown
---
title: <short statement of the reusable fact / pattern>
tags: [aws, gpu, ...]
sourceCases: [RND-YYYYMMDD-NNN]
evidence: [EV-003, EXP-001]
freshnessClass: fast-moving | normal | stable
lastVerified: YYYY-MM-DD
status: candidate
---

## Statement
(the fact / pattern, 3-10 lines, with versions and scope)

## Why we believe it
(what was validated, how; link to .rnd/cases/<CASE>/validation/result.md or experiments/EXP-NNN/result.md)

## When it stops being true
(revisit triggers: version bump, vendor announcement, date)

## How to apply
```
Then:
```bash
python3 .claude/scripts/rnd.py action <CASE> "knowledge candidate: .rnd/knowledge/candidates/<slug>.md"
python3 .claude/scripts/rnd.py index
```
and add the path to `case.json → knowledgePromotion.candidates` (edit via `rnd.py show` + Edit is acceptable for this field).

## Step 3 - Review before promotion
A candidate is promoted only after an independent check (a `claim-verifier` dispatch, or the human). The reviewer confirms: the statement matches the evidence, scope/version is stated, and nothing confidential is included (`python3 .claude/scripts/safety_check.py secrets .rnd/knowledge/candidates/<slug>.md`).

## Step 4 - Promote
Move the file to `.rnd/knowledge/shared/<slug>.md`, set `status: shared` and `promotedAt: YYYY-MM-DD`, keep `sourceCases`. Update `knowledgePromotion.promoted` in the case, then `python3 .claude/scripts/rnd.py index`.

## Maintenance
- `fast-moving` entries older than 30 days (normal 180, stable 365) must be re-verified before an agent relies on them; a Researcher who finds them wrong reports it and the Lead marks the entry `status: superseded` with a pointer to the new case.
- Shared knowledge never gets edited "in passing" by a Builder or Researcher: hooks block those agents from `.rnd/knowledge/`.
