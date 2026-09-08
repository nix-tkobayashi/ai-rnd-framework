#!/usr/bin/env python3
"""rnd.py - R&D Case management CLI (the Lead's write interface to the SSOT).

  python3 .claude/scripts/rnd.py new "<title>" [--type research|experiment|implementation] [--risk standard|high]
                             [--tags a,b] [--keywords x,y] [--question "..."] [--lang ja|en|..] [--target-repo R --target-commit C]
  python3 .claude/scripts/rnd.py search "<query>"                 # existing-case search (index + full text)
  python3 .claude/scripts/rnd.py list [--all] [--state STATE]
  python3 .claude/scripts/rnd.py show <CASE>
  python3 .claude/scripts/rnd.py resume <CASE>                    # session-independent resume summary
  python3 .claude/scripts/rnd.py state <CASE> <STATE> [--note ..] [--force]
  python3 .claude/scripts/rnd.py next <CASE> "<next action>"
  python3 .claude/scripts/rnd.py action <CASE> "<what was done>" [--by lead]
  python3 .claude/scripts/rnd.py research add <CASE> --file report.md --by researcher-official
  python3 .claude/scripts/rnd.py research complete <CASE>
  python3 .claude/scripts/rnd.py report add <CASE> --file report.md --by builder [--exp EXP-001]   # non-research reports
  python3 .claude/scripts/rnd.py agent start <CASE> <agent> "<task>" / agent done <CASE> <agent> [--note ..] [--outcome done|failed|timeout] / agent status <CASE>
  python3 .claude/scripts/rnd.py evidence add <CASE> --claim .. --source .. --source-type official-doc --by researcher-official [..]
                                            [--doi .. --venue .. --peer-reviewed yes|no --artifacts code,data --reproduced-by .. --conditions ..]   # literature
  python3 .claude/scripts/rnd.py evidence check <CASE>            # freshness report
  python3 .claude/scripts/rnd.py experiment new <CASE> "<title>" [--hypothesis ..]
  python3 .claude/scripts/rnd.py experiment set <CASE> EXP-001 --status approved|running|passed|failed|inconclusive|abandoned
  python3 .claude/scripts/rnd.py review init <CASE> [--required-test CMD ...] [--diff-base REF] [--not-required]
  python3 .claude/scripts/rnd.py review status <CASE>             # convergence gate (review_gate.py)
  python3 .claude/scripts/rnd.py findings <CASE> [--all]
  python3 .claude/scripts/rnd.py finding set <CASE> F-01-001 fixed_pending_review|disputed|accepted_risk --note ".." [--by claude|lead]
  python3 .claude/scripts/rnd.py tests run <CASE> [--label baseline|after]
  python3 .claude/scripts/rnd.py validate record <CASE> --status pass|fail|inconclusive --summary ".." [--criteria AC-01=pass ...] [--by validator]
  python3 .claude/scripts/rnd.py decide <CASE> --outcome adopt|reject|defer|partial|inconclusive --summary ".." [--force]
  python3 .claude/scripts/rnd.py archive <CASE>
  python3 .claude/scripts/rnd.py handoff <CASE>                   # regenerate handoff.md
  python3 .claude/scripts/rnd.py stale [--days N] [--apply]
  python3 .claude/scripts/rnd.py index
  python3 .claude/scripts/rnd.py brief                            # compact active-case list (SessionStart)
  python3 .claude/scripts/rnd.py doctor
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rndlib  # noqa: E402
from rndlib import (ROOT, RND_DIR, add_history, die, eprint, load_case, now_iso, read_json, rel,  # noqa: E402
                    save_case, transition, write_json, write_text)

# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #

# Templates per output language. Structural markers (<!-- ... -->) are language-neutral so
# commands like `decide` can fill them in regardless of language.
TEMPLATES: dict[str, dict[str, str]] = {}

TEMPLATES["en"] = {
"brief": """# {id}: {title}

**Type:** {caseType}  **Risk:** {riskLevel}  **Language:** {language}  **Created:** {created}

## Question

{question}

## Scope

- In scope:
- Out of scope:

## Why now / background

## Constraints

## Success criteria

## Related cases

{related}
""",
"synthesis": """# Research Synthesis - {id}

> Research ≠ Decision. This file records what the evidence says. The decision lives in `decision.md`.

## Question

{question}

## Summary of findings

_(fill in after Researcher + Critic reports are in `research/`)_

## Consensus

## Contested / counter-evidence (from Critic)

## Unknowns / needs experiment

## Evidence references

See `evidence.json` (EV-xxx) and `sources.md`.
""",
"sources": """# Sources - {id}

| EV | Source | Type | Retrieved | Freshness | Collected by |
|----|--------|------|-----------|-----------|--------------|
""",
"decision": """# Decision - {id}: {title}

**Status:** pending <!-- status -->

> Decision ≠ Research. `research/synthesis.md` says what is technically true;
> this file says what we do about it for *this* use-case, and why.

## Decision

_(pending)_ <!-- decision -->

## Rationale

<!-- rationale -->

## Alternatives considered

## Conditions / revisit triggers

## Follow-ups
""",
"plan": """# {exp_id}: {title}

**Case:** {case_id}  **Status:** planned  **Designed by:** {by}

## Hypothesis

{hypothesis}

## Environment

## File layout (artifacts/<name>/ for runnable files, experiments/EXP-NNN/logs/ for logs)

## Procedure

1.

## Expected result

## Failure condition

## Acceptance criteria

| AC | Criterion | Measurement |
|----|-----------|-------------|
| AC-01 | | |

## Evidence to collect

## Baseline tests (before change)

## Notes
""",
}

TEMPLATES["ja"] = {
"brief": """# {id}: {title}

**種別:** {caseType}  **リスク:** {riskLevel}  **出力言語:** {language}  **作成:** {created}

## 問い

{question}

## スコープ

- 対象:
- 対象外:

## 背景 / なぜ今か

## 制約

## 成功基準

## 関連 Case

{related}
""",
"synthesis": """# 調査統合 - {id}

> 調査 ≠ 決定。このファイルはエビデンスが何を示すかを記録する。決定は `decision.md` に書く。
> 引用（quote）・コード・コマンド・識別子は原文のまま残し、要約と解釈を日本語で書く。

## 問い

{question}

## 調査結果の要約

_(Researcher と Critic の報告が `research/` に揃ってから記入)_

## 合意点

## 争点・反証（Critic より）

## 未解決 / 実験が必要な点

## エビデンス参照

`evidence.json`（EV-xxx）と `sources.md` を参照。
""",
"sources": """# 出典一覧 - {id}

| EV | 出典 | 種別 | 取得日 | 鮮度 | 収集者 |
|----|------|------|--------|------|--------|
""",
"decision": """# 決定 - {id}: {title}

**Status:** pending <!-- status -->

> 決定 ≠ 調査。`research/synthesis.md` は技術的に何が正しいかを述べ、
> このファイルは *この用途* で何をするか、なぜかを述べる。

## 決定

_(pending)_ <!-- decision -->

## 根拠

<!-- rationale -->

## 検討した代替案

## 前提条件 / 再検討のトリガー

## フォローアップ
""",
"plan": """# {exp_id}: {title}

**Case:** {case_id}  **Status:** planned  **設計者:** {by}

## 仮説

{hypothesis}

## 環境

## ファイル配置（実行ファイルは artifacts/<name>/、ログは experiments/EXP-NNN/logs/）

## 手順

1.

## 期待結果

## 失敗条件

## 受け入れ基準

| AC | 基準 | 測定方法 |
|----|------|----------|
| AC-01 | | |

## 収集するエビデンス

## ベースラインテスト（変更前）

## 備考
""",
}


def tmpl(case: dict, name: str) -> str:
    lang = case.get("language", "en")
    return TEMPLATES.get(lang, TEMPLATES["en"]).get(name) or TEMPLATES["en"][name]


def _case_layout(case_dir: Path, case: dict) -> None:
    for sub in ["research", "reports", "experiments", "reviews", "validation", "artifacts"]:
        (case_dir / sub).mkdir(parents=True, exist_ok=True)
    (case_dir / "artifacts" / ".gitkeep").touch()
    related = "\n".join(f"- {c}" for c in case.get("relatedCases", [])) or "- (none)"
    write_text(case_dir / "brief.md", tmpl(case, "brief").format(related=related, **case), overwrite=False)
    write_text(case_dir / "research" / "synthesis.md", tmpl(case, "synthesis").format(**case), overwrite=False)
    write_text(case_dir / "research" / "sources.md", tmpl(case, "sources").format(**case), overwrite=False)
    if not (case_dir / "research" / "evidence.json").exists():
        write_json(case_dir / "research" / "evidence.json", {"schemaVersion": 1, "caseId": case["id"], "evidence": []})
    write_text(case_dir / "decision.md", tmpl(case, "decision").format(**case), overwrite=False)


# --------------------------------------------------------------------------- #
# new / list / search / show
# --------------------------------------------------------------------------- #

def cmd_new(a: argparse.Namespace) -> int:
    policy = rndlib.load_policy()
    case_id = rndlib.next_case_id()
    slug = rndlib.slugify(a.slug or a.title)
    case_dir = RND_DIR / f"{case_id}-{slug}"
    if case_dir.exists():
        die(f"{case_dir} already exists")
    tags = [t.strip() for t in (a.tags or "").split(",") if t.strip()]
    keywords = [k.strip() for k in (a.keywords or "").split(",") if k.strip()]
    ts = now_iso()
    risk = a.risk
    language = a.lang or rndlib.detect_language((a.question or "") + " " + a.title)
    if language not in rndlib.LANGUAGES:
        die(f"unsupported --lang {language}; known: {', '.join(rndlib.LANGUAGES)}")
    case = {
        "schemaVersion": 1,
        "id": case_id,
        "slug": slug,
        "title": a.title,
        "question": a.question or a.title,
        "summary": "",
        "state": "NEW",
        "caseType": a.type,
        "riskLevel": risk,
        "language": language,
        "tags": tags,
        "keywords": keywords,
        "freshnessClass": rndlib.freshness_class_for(" ".join([a.title, *tags, *keywords]), policy),
        "created": ts,
        "updated": ts,
        "owner": a.owner or "lead",
        "targetRepository": a.target_repo,
        "targetCommit": a.target_commit,
        "relatedCases": [c for c in (a.related or "").split(",") if c],
        "resumedFrom": None,
        "research": {"status": "not_started", "researchers": [], "critics": [], "synthesis": "research/synthesis.md", "evidenceCount": 0, "completedAt": None},
        "experiments": [],
        "review": {
            "required": a.type == "implementation",
            "status": "not_started" if a.type == "implementation" else "not_required",
            "rounds": 0,
            "maxRounds": policy["review"]["maxRounds"],
            "consecutiveClean": 0,
            "requiredCleanRounds": policy["review"]["requiredCleanRounds"][risk],
            "requiredTests": [],
            "diffBase": None,
            "lastRoundVerdict": None,
            "convergedAt": None,
        },
        "validation": {"status": "not_started", "completedAt": None},
        "decision": {"status": "pending", "outcome": None, "summary": "", "recordedAt": None},
        "knowledgePromotion": {"candidates": [], "promoted": []},
        "lastAction": {"at": ts, "by": "lead", "summary": "case created"},
        "nextAction": "TRIAGE: confirm scope in brief.md, decide caseType/risk, then dispatch research",
        "history": [{"at": ts, "event": "created", "by": "lead", "to": "NEW"}],
    }
    errs = rndlib.validate("case", case)
    if errs:
        die("generated case.json is invalid: " + "; ".join(errs))
    case_dir.mkdir(parents=True)
    write_json(case_dir / "case.json", case)
    _case_layout(case_dir, case)
    cmd_handoff(argparse.Namespace(case=case_id, quiet=True))
    _regen_index()
    print(f"created {case_id} at {rel(case_dir)}")
    print(f"  title: {a.title}\n  type: {a.type}  risk: {risk}  freshness: {case['freshnessClass']}  language: {language} ({rndlib.language_name(language)}; research in source languages, outputs in this one)")
    print(f"  next: edit {rel(case_dir / 'brief.md')} then `rnd.py state {case_id} TRIAGE`")
    return 0


def _all_cases() -> list[dict]:
    out = []
    for d in rndlib.case_dirs():
        try:
            c = read_json(d / "case.json")
            c["_dir"] = d
            out.append(c)
        except Exception as exc:  # noqa: BLE001
            eprint(f"warning: cannot read {d / 'case.json'}: {exc}")
    return out


def cmd_list(a: argparse.Namespace) -> int:
    rows = []
    for c in _all_cases():
        if a.state and c["state"] != a.state:
            continue
        if not a.all and c["state"] == "ARCHIVED":
            continue
        rows.append(c)
    if not rows:
        print("(no cases)")
        return 0
    print(f"{'ID':18} {'STATE':18} {'TYPE':14} {'RISK':8} TITLE")
    for c in rows:
        print(f"{c['id']:18} {c['state']:18} {c['caseType']:14} {c['riskLevel']:8} {c['title']}")
    return 0


def _tokenize(q: str) -> list[str]:
    return [t for t in re.split(r"[^\w\-\.]+", q.lower()) if len(t) >= 2]


def search_cases(query: str, limit: int = 10) -> list[tuple[float, dict, list[str]]]:
    """Score cases by title/tags/keywords/decision/synthesis and full-text hits."""
    toks = _tokenize(query)
    if not toks:
        return []
    results = []
    for c in _all_cases():
        score = 0.0
        why: list[str] = []
        fields = {
            "title": (c.get("title", ""), 5.0),
            "tags": (" ".join(c.get("tags", [])), 4.0),
            "keywords": (" ".join(c.get("keywords", [])), 4.0),
            "question": (c.get("question", ""), 3.0),
            "summary": (c.get("summary", ""), 2.0),
            "decision": (c.get("decision", {}).get("summary", ""), 3.0),
        }
        for name, (text, w) in fields.items():
            low = text.lower()
            hits = [t for t in toks if t in low]
            if hits:
                score += w * len(hits)
                why.append(f"{name}:{','.join(hits)}")
        # full text
        ft_hits: dict[str, int] = {}
        for p in rndlib.iter_case_text_files(c["_dir"]):
            try:
                low = p.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            for t in toks:
                n = low.count(t)
                if n:
                    ft_hits[t] = ft_hits.get(t, 0) + n
        if ft_hits:
            score += sum(min(n, 10) * 0.2 for n in ft_hits.values())
            why.append("fulltext:" + ",".join(f"{t}x{n}" for t, n in sorted(ft_hits.items())))
        if query.lower().strip() == c.get("title", "").lower().strip():
            score += 20
        if score > 0:
            results.append((score, c, why))
    results.sort(key=lambda r: -r[0])
    return results[:limit]


def cmd_search(a: argparse.Namespace) -> int:
    res = search_cases(a.query, a.limit)
    if not res:
        print(f"No existing case matches {a.query!r}. -> create a new case: rnd.py new \"<title>\"")
        return 0
    print(f"Similar cases for {a.query!r} (highest first):")
    for score, c, why in res:
        print(f"  {c['id']}  [{c['state']}] {c['title']}  (score {score:.1f})")
        print(f"      {' '.join(why)}")
        if c.get("decision", {}).get("summary"):
            print(f"      decision: {c['decision']['summary'][:120]}")
    top = res[0]
    if top[0] >= 8:
        print(f"\nLikely the same topic -> resume: rnd.py resume {top[1]['id']}")
    else:
        print("\nWeak match -> probably a new case; reference related cases with --related.")
    return 0


def cmd_show(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    c = dict(c)
    c["_dir"] = rel(d)
    print(json.dumps(c, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# resume / handoff
# --------------------------------------------------------------------------- #

def _read_head(path: Path, max_lines: int = 40) -> str:
    if not path.exists():
        return "(missing)"
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    body = [l for l in lines if l.strip() and not l.startswith("> ")]
    return "\n".join(body[:max_lines]) + ("\n..." if len(body) > max_lines else "")


def resume_report(case_ref: str) -> str:
    d, c = load_case(case_ref)
    policy = rndlib.load_policy()
    out: list[str] = []
    out.append(f"# Resume {c['id']}: {c['title']}")
    out.append(f"dir: {rel(d)}")
    out.append("")
    out.append("## Current State")
    out.append(f"{c['state']}  (type={c['caseType']}, risk={c['riskLevel']}, language={c.get('language', 'en')}, updated={c['updated']})")
    out.append("")
    out.append("## Research Summary")
    r = c["research"]
    out.append(f"status={r['status']} researchers={r.get('researchers', [])} critics={r.get('critics', [])} evidence={r.get('evidenceCount', 0)}")
    ev = read_json(d / "research" / "evidence.json", {"evidence": []})
    stale = [e["id"] for e in ev.get("evidence", []) if rndlib.evidence_is_stale(e, policy)]
    if stale:
        out.append(f"STALE evidence (re-verify before relying on it): {', '.join(stale)}")
    out.append(_read_head(d / "research" / "synthesis.md", 25))
    out.append("")
    out.append("## Experiment Status")
    if not c["experiments"]:
        out.append("(none)")
    for e in c["experiments"]:
        out.append(f"- {e['id']} [{e['status']}] {e.get('title', '')}")
    out.append("")
    out.append("## Open Codex Findings")
    rv = c["review"]
    out.append(f"review: required={rv['required']} status={rv['status']} rounds={rv['rounds']}/{rv['maxRounds']} consecutiveClean={rv['consecutiveClean']}/{rv.get('requiredCleanRounds', 1)} lastVerdict={rv.get('lastRoundVerdict')}")
    latest = rndlib.latest_findings(d)
    if latest:
        unresolved = rndlib.unresolved_findings(latest[2], policy)
        if unresolved:
            for f in unresolved:
                out.append(f"- {f['id']} [{f['status']}] {f['severity']} {f['file']}:{f.get('line') or '-'} {f['title']}")
        else:
            out.append("(no unresolved actionable findings in latest round)")
    else:
        out.append("(no review rounds yet)")
    out.append("")
    out.append("## Validation Status")
    v = c["validation"]
    out.append(f"status={v['status']} completedAt={v.get('completedAt')}")
    out.append("")
    out.append("## Decision")
    dc = c["decision"]
    out.append(f"status={dc['status']} outcome={dc.get('outcome')} {dc.get('summary', '')}")
    out.append("")
    out.append("## Agents (timeline)")
    out.extend(agent_status_lines(c))
    out.append("")
    out.append("## Last Action")
    la = c["lastAction"]
    out.append(f"{la['at']} by {la['by']}: {la['summary']}")
    out.append("")
    out.append("## Next Action")
    out.append(c.get("nextAction") or "(not set)")
    return "\n".join(out)


def cmd_resume(a: argparse.Namespace) -> int:
    print(resume_report(a.case))
    return 0


def cmd_handoff(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    text = resume_report(a.case)
    text = "# Handoff (auto-generated by `rnd.py handoff`; regenerate, do not hand-edit)\n\n" + text.split("\n", 1)[1]
    write_text(d / "handoff.md", text + "\n")
    if not getattr(a, "quiet", False):
        print(f"wrote {rel(d / 'handoff.md')}")
    return 0


# --------------------------------------------------------------------------- #
# state / next / action
# --------------------------------------------------------------------------- #

def cmd_state(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    if a.force and not a.note:
        die("--force requires --note explaining why")
    try:
        transition(c, a.state, by=a.by, note=a.note or "", force=a.force)
    except ValueError as exc:
        die(str(exc))
    if a.next:
        c["nextAction"] = a.next
    save_case(d, c, action_by=a.by, action=f"state -> {a.state}" + (f" ({a.note})" if a.note else ""))
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    _regen_index()
    print(f"{c['id']}: {a.state}")
    return 0


def cmd_next(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    c["nextAction"] = a.text
    save_case(d, c, action_by=a.by, action="nextAction updated")
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    print("ok")
    return 0


def cmd_action(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    add_history(c, "action", by=a.by, note=a.text)
    save_case(d, c, action_by=a.by, action=a.text)
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    print("ok")
    return 0


# --------------------------------------------------------------------------- #
# research / evidence
# --------------------------------------------------------------------------- #

def cmd_research_add(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    if a.by.split("-")[0] in ("builder", "validator", "codex", "reviewer") and not a.force:
        die(f"'{a.by}' is not a research agent - use `rnd.py report add <CASE> --file .. --by {a.by}` (or --force)")
    src = Path(a.file)
    if not src.exists():
        die(f"file not found: {src}")
    by = a.by
    dest = d / "research" / f"{rndlib.slugify(by)}.md"
    if dest.exists() and not a.overwrite:
        dest = d / "research" / f"{rndlib.slugify(by)}-{int(time.time())}.md"
    shutil.copyfile(src, dest)
    r = c["research"]
    r["status"] = "in_progress" if r["status"] == "not_started" else r["status"]
    key = "critics" if by.startswith("critic") else "researchers"
    if by not in r.setdefault(key, []):
        r[key].append(by)
    if c["state"] in ("NEW", "TRIAGE"):
        transition(c, "RESEARCHING", by="lead", note="first research report recorded", force=True)
    add_history(c, "research.report", by="lead", note=f"{by} -> {rel(dest)}")
    save_case(d, c, action="research report recorded: " + by)
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    print(f"saved {rel(dest)}")
    return 0


def cmd_research_complete(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    r = c["research"]
    if not r.get("critics") and not a.force:
        die("no Critic report recorded (principle 1: Researcher and Critic are separate). Use --force to override with a note.")
    r["status"] = "complete"
    r["completedAt"] = now_iso()
    ev = read_json(d / "research" / "evidence.json", {"evidence": []})
    r["evidenceCount"] = len(ev.get("evidence", []))
    add_history(c, "research.complete", by="lead", note=a.note or "")
    save_case(d, c, action="research complete")
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    print(f"research complete ({r['evidenceCount']} evidence items). Next: DESIGNING / BUILDING / DECIDED depending on case type.")
    return 0


def cmd_evidence_add(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    policy = rndlib.load_policy()
    path = d / "research" / "evidence.json"
    ev = read_json(path, {"schemaVersion": 1, "caseId": c["id"], "evidence": []})
    seq = len(ev["evidence"]) + 1
    ts = now_iso()
    item = {
        "id": f"EV-{seq:03d}",
        "claim": a.claim,
        "source": a.source,
        "sourceType": a.source_type,
        "created": a.created or ts,
        "retrievedAt": ts,
        "lastVerified": ts,
        "freshnessClass": a.freshness or rndlib.freshness_class_for(a.claim + " " + a.source, policy),
        "confidence": a.confidence,
        "collectedBy": a.by,
        "status": "active",
    }
    if a.quote:
        item["quote"] = a.quote
    if a.interpretation:
        item["interpretation"] = a.interpretation
    if a.source_version:
        item["sourceVersion"] = a.source_version
    if a.doi:
        item["doi"] = a.doi
    if a.venue:
        item["venue"] = a.venue
    if a.peer_reviewed is not None:
        item["peerReviewed"] = a.peer_reviewed == "yes"
    if a.artifacts:
        item["artifactsAvailable"] = [x.strip() for x in a.artifacts.split(",") if x.strip()]
    if a.reproduced_by:
        item["reproducedBy"] = a.reproduced_by
    if a.conditions:
        item["conditions"] = a.conditions
    if a.supports:
        item["supports"] = a.supports.split(",")
    if a.contradicts:
        item["contradicts"] = a.contradicts.split(",")
    ev["evidence"].append(item)
    errs = rndlib.validate("evidence", ev)
    if errs:
        die("evidence.json would be invalid: " + "; ".join(errs))
    write_json(path, ev)
    with open(d / "research" / "sources.md", "a", encoding="utf-8") as f:
        f.write(f"| {item['id']} | {a.source} | {a.source_type} | {ts[:10]} | {item['freshnessClass']} | {a.by} |\n")
    c["research"]["evidenceCount"] = len(ev["evidence"])
    save_case(d, c, action=f"evidence {item['id']} added by {a.by}")
    print(item["id"])
    return 0


def cmd_evidence_check(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    policy = rndlib.load_policy()
    ev = read_json(d / "research" / "evidence.json", {"evidence": []})
    if not ev["evidence"]:
        print("(no evidence)")
        return 0
    stale = 0
    for e in ev["evidence"]:
        s = rndlib.evidence_is_stale(e, policy)
        stale += s
        print(f"{e['id']} {'STALE ' if s else 'fresh '} {e['freshnessClass']:12} verified={e.get('lastVerified') or e.get('retrievedAt')} {e['claim'][:70]}")
    print(f"{stale}/{len(ev['evidence'])} stale -> re-verify primary sources before relying on them")
    return 2 if stale else 0


# --------------------------------------------------------------------------- #
# experiments
# --------------------------------------------------------------------------- #

def cmd_experiment_new(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    seq = len(c["experiments"]) + 1
    exp_id = f"EXP-{seq:03d}"
    edir = d / "experiments" / exp_id
    (edir / "logs").mkdir(parents=True, exist_ok=True)
    (edir / "logs" / ".gitkeep").touch()
    manifest = {
        "schemaVersion": 1,
        "id": exp_id,
        "caseId": c["id"],
        "title": a.title,
        "status": "planned",
        "designedBy": a.by,
        "approvedBy": None,
        "hypothesis": a.hypothesis or "TBD",
        "environment": {"description": "TBD", "worktree": None},
        "procedure": ["TBD"],
        "expectedResult": "TBD",
        "failureCondition": "TBD",
        "acceptanceCriteria": [{"id": "AC-01", "criterion": "TBD", "measurement": "TBD", "result": None}],
        "evidence": [],
        "result": "result.md",
        "created": now_iso(),
        "startedAt": None,
        "finishedAt": None,
    }
    errs = rndlib.validate("experiment", manifest)
    if errs:
        die("manifest invalid: " + "; ".join(errs))
    write_json(edir / "manifest.json", manifest)
    write_text(edir / "plan.md", tmpl(c, "plan").format(exp_id=exp_id, title=a.title, case_id=c["id"], by=a.by, hypothesis=a.hypothesis or ""), overwrite=False)
    c["experiments"].append({"id": exp_id, "title": a.title, "status": "planned", "worktree": None})
    if c["state"] in ("RESEARCHING", "TRIAGE", "NEW"):
        transition(c, "DESIGNING", by="lead", note=f"{exp_id} designed", force=True)
    add_history(c, "experiment.new", by="lead", note=exp_id)
    save_case(d, c, action=f"{exp_id} created")
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    print(f"created {rel(edir)} (edit plan.md + manifest.json, then `experiment set {c['id']} {exp_id} --status approved`)")
    return 0


def cmd_experiment_set(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    edir = d / "experiments" / a.exp
    if not edir.exists():
        die(f"{a.exp} not found")
    m = read_json(edir / "manifest.json")
    if a.status == "approved":
        placeholders = [k for k in ("hypothesis", "expectedResult", "failureCondition") if m.get(k) in ("TBD", "")]
        if placeholders and not a.force:
            die(f"cannot approve: manifest still has TBD in {placeholders}")
        m["approvedBy"] = a.by
    if a.status == "running":
        m["startedAt"] = m.get("startedAt") or now_iso()
        if c["state"] in ("DESIGNING",):
            transition(c, "EXPERIMENTING", by="lead", note=a.exp, force=True)
    if a.status in ("passed", "failed", "inconclusive", "abandoned"):
        m["finishedAt"] = now_iso()
    m["status"] = a.status
    if a.worktree is not None:
        m.setdefault("environment", {})["worktree"] = a.worktree or None
    errs = rndlib.validate("experiment", m)
    if errs:
        die("manifest invalid: " + "; ".join(errs))
    write_json(edir / "manifest.json", m)
    for e in c["experiments"]:
        if e["id"] == a.exp:
            e["status"] = a.status
            if a.worktree is not None:
                e["worktree"] = a.worktree or None
    add_history(c, "experiment.status", by=a.by, note=f"{a.exp} -> {a.status}" + (f": {a.note}" if a.note else ""))
    save_case(d, c, action=f"{a.exp} {a.status}")
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    print(f"{a.exp}: {a.status}")
    return 0


# --------------------------------------------------------------------------- #
# review / findings
# --------------------------------------------------------------------------- #

def cmd_review_init(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    policy = rndlib.load_policy()
    rv = c["review"]
    if a.not_required:
        if a.note is None:
            die("--not-required needs --note (why no code changed)")
        rv["required"] = False
        rv["status"] = "not_required"
    else:
        rv["required"] = True
        rv["status"] = "not_started" if rv["rounds"] == 0 else rv["status"]
    if a.required_test:
        rv["requiredTests"] = list(a.required_test)
    if a.diff_base is not None:
        rv["diffBase"] = a.diff_base or None
    if a.risk:
        c["riskLevel"] = a.risk
        rv["requiredCleanRounds"] = policy["review"]["requiredCleanRounds"][a.risk]
    rv["maxRounds"] = a.max_rounds or rv["maxRounds"]
    add_history(c, "review.init", by="lead", note=a.note or f"tests={rv['requiredTests']} base={rv['diffBase']}")
    save_case(d, c, action="review initialised")
    print(json.dumps(rv, indent=2))
    return 0


def cmd_review_status(a: argparse.Namespace) -> int:
    return subprocess.call([sys.executable, str(rndlib.SCRIPTS_DIR / "review_gate.py"), a.case])


def cmd_findings(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    policy = rndlib.load_policy()
    rounds = rndlib.load_findings_rounds(d)
    if not rounds:
        print("(no review rounds)")
        return 0
    for n, rd, fj in rounds:
        if not a.all and n != rounds[-1][0]:
            continue
        print(f"round-{n:02d} verdict={fj['verdict']} at={fj['reviewedAt']} findings={len(fj['findings'])}")
        for f in fj["findings"]:
            if not a.all and f["status"] not in policy["review"]["unresolvedStatuses"]:
                continue
            print(f"  {f['id']} [{f['status']}] {f['severity']}/{f['category']} {f['file']}:{f.get('line') or '-'}  {f['title']}  (fp {f['fingerprint']}, reopen {f.get('reopenCount', 0)})")
    return 0


def cmd_finding_set(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    policy = rndlib.load_policy()["review"]
    by = a.by
    allowed = {"claude": policy["claudeMaySet"], "lead": policy["claudeMaySet"] + policy["leadMaySet"]}.get(by)
    if allowed is None:
        die("--by must be claude or lead (codex states are set only by .claude/scripts/codex_review.py)")
    if a.status not in allowed:
        die(f"'{by}' may not set status '{a.status}'. Allowed: {allowed}. "
            f"'confirmed_fixed' / 'false_positive' require a Codex re-review round (principle 4).")
    if a.status in ("disputed", "accepted_risk") and not a.note:
        die(f"--note is required for '{a.status}'")
    latest = rndlib.latest_findings(d)
    if not latest:
        die("no review rounds")
    n, rd, fj = latest
    for f in fj["findings"]:
        if f["id"] == a.finding:
            if f["status"] in ("confirmed_fixed", "false_positive"):
                die(f"{a.finding} is already {f['status']}")
            f["status"] = a.status
            f.setdefault("statusHistory", []).append({"at": now_iso(), "status": a.status, "by": by, "note": a.note or ""})
            break
    else:
        die(f"{a.finding} not found in round-{n:02d}")
    errs = rndlib.validate("findings", fj)
    if errs:
        die("findings.json invalid: " + "; ".join(errs))
    write_json(rd / "findings.json", fj)
    add_history(c, "finding.status", by=by, note=f"{a.finding} -> {a.status}" + (f": {a.note}" if a.note else ""))
    save_case(d, c, action_by=by, action=f"{a.finding} -> {a.status}")
    print(f"{a.finding}: {a.status} (Codex re-review required to confirm)")
    return 0


# --------------------------------------------------------------------------- #
# reports (non-research) / agent timeline
# --------------------------------------------------------------------------- #

def cmd_report_add(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    src = Path(a.file)
    if not src.exists():
        die(f"file not found: {src}")
    if a.exp:
        edir = d / "experiments" / a.exp
        if not edir.exists():
            die(f"{a.exp} not found")
        dest = edir / "result.md"
        if dest.exists() and not a.overwrite:
            dest = edir / f"report-{rndlib.slugify(a.by)}-{int(time.time())}.md"
    else:
        (d / "reports").mkdir(exist_ok=True)
        dest = d / "reports" / f"{rndlib.slugify(a.by)}.md"
        if dest.exists() and not a.overwrite:
            dest = d / "reports" / f"{rndlib.slugify(a.by)}-{int(time.time())}.md"
    shutil.copyfile(src, dest)
    add_history(c, "report", by="lead", note=f"{a.by} -> {rel(dest)}")
    save_case(d, c, action=f"report recorded: {a.by}")
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    print(f"saved {rel(dest)}")
    return 0


def _open_dispatches(c: dict) -> list[dict]:
    return [t for t in c.get("timeline", []) if not t.get("finishedAt")]


def cmd_agent_start(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    policy = rndlib.load_policy()
    open_now = _open_dispatches(c)
    if len(open_now) >= policy["concurrency"]["maxAgents"] and not a.force:
        die(f"{len(open_now)} agents already in flight (maxAgents={policy['concurrency']['maxAgents']}); --force to override")
    c.setdefault("timeline", []).append({"agent": a.agent, "task": a.task, "startedAt": now_iso(), "finishedAt": None, "seconds": None, "outcome": None})
    save_case(d, c, action=f"dispatched {a.agent}")
    print(f"{a.agent} started ({len(open_now) + 1} in flight)")
    return 0


def cmd_agent_done(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    entries = [t for t in _open_dispatches(c) if t["agent"] == a.agent]
    if not entries:
        die(f"no open dispatch for '{a.agent}' (rnd.py agent status {c['id']})")
    t = entries[0]
    t["finishedAt"] = now_iso()
    started = rndlib.parse_iso(t["startedAt"])
    finished = rndlib.parse_iso(t["finishedAt"])
    t["seconds"] = round((finished - started).total_seconds(), 1) if started and finished else None
    t["outcome"] = a.outcome
    if a.note:
        t["note"] = a.note
    add_history(c, "agent.done", by="lead", note=f"{a.agent} {a.outcome} in {t['seconds']}s" + (f": {a.note}" if a.note else ""))
    save_case(d, c, action=f"{a.agent} {a.outcome} ({t['seconds']}s)")
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    print(f"{a.agent}: {a.outcome} after {t['seconds']}s")
    return 0


def agent_status_lines(c: dict, stale_minutes: int = 15) -> list[str]:
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    tl = c.get("timeline", [])
    if not tl:
        return ["(no agent dispatches recorded)"]
    for t in tl:
        if t.get("finishedAt"):
            out.append(f"- {t['agent']:20} {t.get('outcome') or 'done':8} {t.get('seconds', 0):>8}s  {t['task'][:70]}")
        else:
            started = rndlib.parse_iso(t["startedAt"])
            el = (now - started).total_seconds() if started else 0
            flag = "  <- check: no report yet" if el > stale_minutes * 60 else ""
            out.append(f"- {t['agent']:20} RUNNING  {el:>8.0f}s  {t['task'][:70]}{flag}")
    total = sum(t.get("seconds") or 0 for t in tl if t.get("finishedAt"))
    out.append(f"total recorded agent time: {total:.0f}s over {len(tl)} dispatch(es)")
    return out


def cmd_agent_status(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    print("\n".join(agent_status_lines(c)))
    return 0


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #

def run_required_tests(case_dir: Path, case: dict, timeout: int = 900) -> list[dict]:
    """Run review.requiredTests and return [{name,status,note,exit,seconds}]."""
    results = []
    for cmd in case["review"].get("requiredTests", []):
        t0 = time.time()
        try:
            r = subprocess.run(cmd, shell=True, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
            status = "PASS" if r.returncode == 0 else "FAIL"
            note = (r.stdout + r.stderr)[-2000:]
            code = r.returncode
        except subprocess.TimeoutExpired:
            status, note, code = "ERROR", f"timeout after {timeout}s", -1
        results.append({"name": cmd, "status": status, "note": note.strip(), "exit": code, "seconds": round(time.time() - t0, 1)})
    return results


def cmd_tests_run(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    if not c["review"].get("requiredTests"):
        die("no requiredTests configured: rnd.py review init <CASE> --required-test '<cmd>'")
    results = run_required_tests(d, c)
    ts = now_iso()
    (d / "validation").mkdir(exist_ok=True)
    out = {"caseId": c["id"], "label": a.label, "at": ts, "results": results}
    path = d / "validation" / f"tests-{a.label}.json"
    write_json(path, out)
    allpass = all(r["status"] == "PASS" for r in results)
    for r in results:
        print(f"{r['status']:5} {r['seconds']:6}s  {r['name']}")
    print(f"-> {rel(path)} ({'ALL PASS' if allpass else 'FAILURES'})")
    add_history(c, "tests", by=a.by, note=f"{a.label}: {'PASS' if allpass else 'FAIL'}")
    save_case(d, c, action_by=a.by, action=f"tests {a.label}: {'PASS' if allpass else 'FAIL'}")
    return 0 if allpass else 2


# --------------------------------------------------------------------------- #
# validation / decision / archive
# --------------------------------------------------------------------------- #

def cmd_validate_record(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    if a.by in ("builder", "isolated-builder"):
        die("principle 8: the Builder must not record the final PASS. Use --by validator (or lead).")
    if c["review"]["required"] and c["review"]["status"] not in ("converged",) and a.status == "pass" and not a.force:
        die("Codex review has not converged (principle 3/6). Run review rounds first, or --force with --note for research-only validation.")
    criteria = []
    for item in a.criteria or []:
        k, _, v = item.partition("=")
        criteria.append({"id": k, "result": v or "inconclusive"})
    ts = now_iso()
    result = {"caseId": c["id"], "status": a.status, "validator": a.by, "summary": a.summary, "criteria": criteria,
              "reproducibility": a.reproducibility, "at": ts, "note": a.note or ""}
    (d / "validation").mkdir(exist_ok=True)
    write_json(d / "validation" / "result.json", result)
    md = [f"# Validation - {c['id']}", "", f"**Status:** {a.status.upper()}  **Validator:** {a.by}  **At:** {ts}", "", "## Summary", "", a.summary, ""]
    if criteria:
        md += ["## Acceptance criteria", "", "| AC | Result |", "|----|--------|"] + [f"| {x['id']} | {x['result']} |" for x in criteria] + [""]
    md += ["## Reproducibility", "", a.reproducibility or "(not stated)", ""]
    if a.note:
        md += ["## Notes", "", a.note, ""]
    write_text(d / "validation" / "result.md", "\n".join(md))
    c["validation"] = {"status": a.status, "validator": a.by, "result": "validation/result.json", "completedAt": ts}
    if c["state"] in ("REVIEWING", "EXPERIMENTING", "BUILDING"):
        transition(c, "VALIDATING", by=a.by, note="validation recorded", force=True)
    add_history(c, "validation", by=a.by, note=f"{a.status}: {a.summary[:120]}")
    save_case(d, c, action_by=a.by, action=f"validation {a.status}")
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    print(f"validation recorded: {a.status}")
    return 0


def completion_gaps(case_dir: Path, c: dict) -> list[str]:
    """Return unmet completion criteria per SPEC §43 for the case type."""
    gaps = []
    ct = c["caseType"]
    r, rv, v = c["research"], c["review"], c["validation"]
    if r["status"] != "complete":
        gaps.append("Research not complete (rnd.py research complete)")
    if not r.get("critics"):
        gaps.append("No Critic report recorded")
    ev = read_json(case_dir / "research" / "evidence.json", {"evidence": []})
    if not ev.get("evidence"):
        gaps.append("No evidence recorded in research/evidence.json")
    if ct in ("experiment", "implementation"):
        if ct == "experiment" and not any(e["status"] in ("passed", "failed", "inconclusive") for e in c["experiments"]):
            gaps.append("No experiment executed to completion")
        if rv["required"] and rv["status"] != "converged":
            gaps.append(f"Codex review not converged (status={rv['status']})")
        if v["status"] not in ("pass", "fail", "inconclusive"):
            gaps.append("Validation not recorded")
    if ct == "implementation":
        if v["status"] != "pass":
            gaps.append(f"Validator did not PASS (status={v['status']})")
        latest = rndlib.latest_findings(case_dir)
        if latest and any(f["severity"] == "blocking" and f["status"] not in ("confirmed_fixed", "false_positive") for f in latest[2]["findings"]):
            gaps.append("Unresolved blocking finding")
    return gaps


def cmd_decide(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    gaps = completion_gaps(d, c)
    if gaps and not a.force:
        eprint("completion criteria not met:")
        for g in gaps:
            eprint("  - " + g)
        die("use --force --note '...' to record a decision anyway (e.g. outcome=inconclusive/defer)")
    if a.force and not a.note:
        die("--force requires --note")
    ts = now_iso()
    c["decision"] = {"status": "recorded", "outcome": a.outcome, "summary": a.summary, "recordedAt": ts}
    body = (d / "decision.md").read_text(encoding="utf-8") if (d / "decision.md").exists() else tmpl(c, "decision").format(**c)
    body = body.replace("**Status:** pending", f"**Status:** recorded ({a.outcome}) at {ts}", 1)
    decided = f"**{a.outcome.upper()}** - {a.summary}"
    if "_(pending)_" in body:
        body = body.replace("_(pending)_ <!-- decision -->", decided, 1).replace("_(pending)_", decided, 1)
    if a.rationale:
        if "<!-- rationale -->" in body:
            body = body.replace("<!-- rationale -->", a.rationale, 1)
        else:
            body = body.replace("## Rationale\n", f"## Rationale\n\n{a.rationale}\n", 1)
    if a.force:
        body += f"\n\n> Recorded with --force. Unmet criteria: {'; '.join(gaps)}. Note: {a.note}\n"
    write_text(d / "decision.md", body)
    transition(c, "DECIDED", by=a.by, note=a.note or a.summary[:120], force=True)
    c["nextAction"] = "ARCHIVE: promote reusable knowledge (knowledge-promotion skill) then rnd.py archive"
    save_case(d, c, action_by=a.by, action=f"decision recorded: {a.outcome}")
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    _regen_index()
    print(f"{c['id']} DECIDED: {a.outcome}")
    return 0


def cmd_archive(a: argparse.Namespace) -> int:
    d, c = load_case(a.case)
    if c["state"] != "DECIDED" and not a.force:
        die(f"state is {c['state']}, must be DECIDED (or --force --note)")
    if a.force and not a.note:
        die("--force requires --note")
    transition(c, "ARCHIVED", by=a.by, note=a.note or "", force=a.force)
    c["nextAction"] = "(archived) - resume with rnd.py resume if the topic comes back"
    save_case(d, c, action_by=a.by, action="archived")
    cmd_handoff(argparse.Namespace(case=c["id"], quiet=True))
    _regen_index()
    print(f"{c['id']} ARCHIVED")
    return 0


# --------------------------------------------------------------------------- #
# stale / index / brief / doctor
# --------------------------------------------------------------------------- #

def cmd_stale(a: argparse.Namespace) -> int:
    import datetime as dt
    policy = rndlib.load_policy()
    days = a.days or policy["stale"]["caseInactiveDays"]
    now = dt.datetime.now(dt.timezone.utc)
    n = 0
    for c in _all_cases():
        if c["state"] in ("ARCHIVED", "DECIDED", "STALE"):
            continue
        upd = rndlib.parse_iso(c["updated"])
        if upd and (now - upd).days > days:
            n += 1
            print(f"{c['id']} [{c['state']}] inactive {(now - upd).days}d: {c['title']}")
            if a.apply:
                d = c.pop("_dir")
                transition(c, "STALE", by="lead", note=f"inactive > {days} days")
                save_case(d, c, action="marked STALE")
    print(f"{n} stale case(s)" + ("" if a.apply else " (use --apply to mark STALE)"))
    return 0


def _regen_index() -> None:
    subprocess.call([sys.executable, str(rndlib.SCRIPTS_DIR / "generate_index.py"), "--quiet"])


def cmd_index(a: argparse.Namespace) -> int:
    return subprocess.call([sys.executable, str(rndlib.SCRIPTS_DIR / "generate_index.py")])


def cmd_brief(a: argparse.Namespace) -> int:
    cases = [c for c in _all_cases() if c["state"] != "ARCHIVED"]
    if not cases:
        print(f"ai-rnd-workspace engine {rndlib.engine_version()}: no active R&D cases. Start with `python3 .claude/scripts/rnd.py search \"<topic>\"` then `rnd.py new`.")
        return 0
    print(f"ai-rnd-workspace engine {rndlib.engine_version()}: {len(cases)} active R&D case(s). Case files are the source of truth, not this conversation.")
    for c in sorted(cases, key=lambda x: x["updated"], reverse=True)[:10]:
        print(f"- {c['id']} [{c['state']}] {c['title']} -> next: {c.get('nextAction', '')[:100]}")
    print("Resume with: python3 .claude/scripts/rnd.py resume <CASE>")
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    return subprocess.call([sys.executable, str(rndlib.SCRIPTS_DIR / "rnd_doctor.py")])


# --------------------------------------------------------------------------- #
# arg parsing
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rnd.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"ai-rnd-workspace engine {rndlib.engine_version()}")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("new"); p.add_argument("title"); p.add_argument("--type", choices=["research", "experiment", "implementation"], default="research")
    p.add_argument("--risk", choices=["standard", "high"], default="standard"); p.add_argument("--tags"); p.add_argument("--keywords")
    p.add_argument("--question"); p.add_argument("--slug"); p.add_argument("--owner"); p.add_argument("--target-repo"); p.add_argument("--target-commit"); p.add_argument("--related")
    p.add_argument("--lang", help="output language code (ISO 639-1); default: detected from the question")
    p.set_defaults(fn=cmd_new)

    p = sp.add_parser("search"); p.add_argument("query"); p.add_argument("--limit", type=int, default=10); p.set_defaults(fn=cmd_search)
    p = sp.add_parser("list"); p.add_argument("--all", action="store_true"); p.add_argument("--state"); p.set_defaults(fn=cmd_list)
    p = sp.add_parser("show"); p.add_argument("case"); p.set_defaults(fn=cmd_show)
    p = sp.add_parser("resume"); p.add_argument("case"); p.set_defaults(fn=cmd_resume)
    p = sp.add_parser("handoff"); p.add_argument("case"); p.set_defaults(fn=cmd_handoff, quiet=False)

    p = sp.add_parser("state"); p.add_argument("case"); p.add_argument("state", choices=rndlib.ALL_STATES); p.add_argument("--note"); p.add_argument("--next"); p.add_argument("--force", action="store_true"); p.add_argument("--by", default="lead"); p.set_defaults(fn=cmd_state)
    p = sp.add_parser("next"); p.add_argument("case"); p.add_argument("text"); p.add_argument("--by", default="lead"); p.set_defaults(fn=cmd_next)
    p = sp.add_parser("action"); p.add_argument("case"); p.add_argument("text"); p.add_argument("--by", default="lead"); p.set_defaults(fn=cmd_action)

    r = sp.add_parser("research"); rs = r.add_subparsers(dest="sub", required=True)
    p = rs.add_parser("add"); p.add_argument("case"); p.add_argument("--file", required=True); p.add_argument("--by", required=True); p.add_argument("--overwrite", action="store_true"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_research_add)
    p = rs.add_parser("complete"); p.add_argument("case"); p.add_argument("--note"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_research_complete)

    rp = sp.add_parser("report"); rps = rp.add_subparsers(dest="sub", required=True)
    p = rps.add_parser("add"); p.add_argument("case"); p.add_argument("--file", required=True); p.add_argument("--by", required=True); p.add_argument("--exp"); p.add_argument("--overwrite", action="store_true"); p.set_defaults(fn=cmd_report_add)

    ag = sp.add_parser("agent"); ags = ag.add_subparsers(dest="sub", required=True)
    p = ags.add_parser("start"); p.add_argument("case"); p.add_argument("agent"); p.add_argument("task"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_agent_start)
    p = ags.add_parser("done"); p.add_argument("case"); p.add_argument("agent"); p.add_argument("--note"); p.add_argument("--outcome", choices=["done", "failed", "timeout", "cancelled"], default="done"); p.set_defaults(fn=cmd_agent_done)
    p = ags.add_parser("status"); p.add_argument("case"); p.set_defaults(fn=cmd_agent_status)

    e = sp.add_parser("evidence"); es = e.add_subparsers(dest="sub", required=True)
    p = es.add_parser("add"); p.add_argument("case"); p.add_argument("--claim", required=True); p.add_argument("--source", required=True)
    p.add_argument("--source-type", required=True, choices=["official-doc", "release-note", "github-issue", "github-code", "blog", "paper", "experiment", "command-output", "internal-doc", "other"])
    p.add_argument("--by", required=True); p.add_argument("--confidence", choices=["high", "medium", "low"], default="medium"); p.add_argument("--freshness", choices=["fast-moving", "normal", "stable"])
    p.add_argument("--quote"); p.add_argument("--interpretation"); p.add_argument("--source-version"); p.add_argument("--created"); p.add_argument("--supports"); p.add_argument("--contradicts")
    p.add_argument("--doi"); p.add_argument("--venue"); p.add_argument("--peer-reviewed", choices=["yes", "no"]); p.add_argument("--artifacts", help="comma list: code,data,models,none"); p.add_argument("--reproduced-by"); p.add_argument("--conditions")
    p.set_defaults(fn=cmd_evidence_add)
    p = es.add_parser("check"); p.add_argument("case"); p.set_defaults(fn=cmd_evidence_check)

    x = sp.add_parser("experiment"); xs = x.add_subparsers(dest="sub", required=True)
    p = xs.add_parser("new"); p.add_argument("case"); p.add_argument("title"); p.add_argument("--hypothesis"); p.add_argument("--by", default="experiment-designer"); p.set_defaults(fn=cmd_experiment_new)
    p = xs.add_parser("set"); p.add_argument("case"); p.add_argument("exp"); p.add_argument("--status", required=True, choices=["planned", "approved", "running", "passed", "failed", "inconclusive", "abandoned"])
    p.add_argument("--worktree"); p.add_argument("--note"); p.add_argument("--by", default="lead"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_experiment_set)

    v = sp.add_parser("review"); vs = v.add_subparsers(dest="sub", required=True)
    p = vs.add_parser("init"); p.add_argument("case"); p.add_argument("--required-test", action="append"); p.add_argument("--diff-base"); p.add_argument("--risk", choices=["standard", "high"]); p.add_argument("--max-rounds", type=int); p.add_argument("--not-required", action="store_true"); p.add_argument("--note"); p.set_defaults(fn=cmd_review_init)
    p = vs.add_parser("status"); p.add_argument("case"); p.set_defaults(fn=cmd_review_status)

    p = sp.add_parser("findings"); p.add_argument("case"); p.add_argument("--all", action="store_true"); p.set_defaults(fn=cmd_findings)
    f = sp.add_parser("finding"); fs = f.add_subparsers(dest="sub", required=True)
    p = fs.add_parser("set"); p.add_argument("case"); p.add_argument("finding"); p.add_argument("status", choices=rndlib.FINDING_STATUSES); p.add_argument("--note"); p.add_argument("--by", default="claude"); p.set_defaults(fn=cmd_finding_set)

    t = sp.add_parser("tests"); ts_ = t.add_subparsers(dest="sub", required=True)
    p = ts_.add_parser("run"); p.add_argument("case"); p.add_argument("--label", default="after"); p.add_argument("--by", default="builder"); p.set_defaults(fn=cmd_tests_run)

    va = sp.add_parser("validate"); vas = va.add_subparsers(dest="sub", required=True)
    p = vas.add_parser("record"); p.add_argument("case"); p.add_argument("--status", required=True, choices=["pass", "fail", "inconclusive"]); p.add_argument("--summary", required=True)
    p.add_argument("--criteria", action="append"); p.add_argument("--reproducibility"); p.add_argument("--note"); p.add_argument("--by", default="validator"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_validate_record)

    p = sp.add_parser("decide"); p.add_argument("case"); p.add_argument("--outcome", required=True, choices=["adopt", "reject", "defer", "partial", "inconclusive"]); p.add_argument("--summary", required=True)
    p.add_argument("--rationale"); p.add_argument("--note"); p.add_argument("--force", action="store_true"); p.add_argument("--by", default="lead"); p.set_defaults(fn=cmd_decide)
    p = sp.add_parser("archive"); p.add_argument("case"); p.add_argument("--note"); p.add_argument("--force", action="store_true"); p.add_argument("--by", default="lead"); p.set_defaults(fn=cmd_archive)
    p = sp.add_parser("stale"); p.add_argument("--days", type=int); p.add_argument("--apply", action="store_true"); p.set_defaults(fn=cmd_stale)
    p = sp.add_parser("index"); p.set_defaults(fn=cmd_index)
    p = sp.add_parser("brief"); p.set_defaults(fn=cmd_brief)
    p = sp.add_parser("doctor"); p.set_defaults(fn=cmd_doctor)
    return ap


READ_ONLY_CMDS = {"search", "list", "show", "resume", "findings", "brief", "doctor", "index", "handoff", "stale"}


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        rc = a.fn(a) or 0
    except FileNotFoundError as exc:
        die(str(exc))
        return 1
    # every mutating command keeps .rnd/index.json + INDEX.md + .rnd/knowledge/catalog.json in sync
    if a.cmd not in READ_ONLY_CMDS and not (a.cmd == "agent" and getattr(a, "sub", "") == "status"):
        _regen_index()
    return rc


if __name__ == "__main__":
    sys.exit(main())
