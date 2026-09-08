#!/usr/bin/env python3
"""codex_review.py - run one independent Codex CLI review round for a case (SPEC §20-§25).

  python3 .claude/scripts/codex_review.py <CASE> [--diff-base REF] [--paths P ...] [--timeout SEC]
                                  [--skip-tests] [--focus "..."] [--dry-run] [--allow-empty]

What one round does (Claude wrapper -> Codex CLI -> Codex model):
  1. builds the diff to review (working tree vs HEAD, or vs --diff-base / review.diffBase)
  2. runs review.requiredTests and records reviews/round-NN/tests.json        (Tests -> Codex)
  3. sends the diff + case context + the previous round's pending findings to `codex exec`
     in a read-only sandbox, asking for strict JSON (.claude/schemas/codex-review-output.schema.json)
  4. merges Codex's answer with the previous round:
        fixed_pending_review + confirmed_fixed  -> confirmed_fixed   (only Codex can do this)
        fixed_pending_review + still_open       -> open, reopenCount+1
        disputed + false_positive               -> false_positive
        new finding whose fingerprint matches a confirmed_fixed one -> re-opened (oscillation signal)
  5. writes reviews/round-NN/{prompt.md,diff.patch,codex_output.md,findings.json,tests.json,meta.json}
  6. updates case.json (rounds, verdict, consecutiveClean) and applies the review gate.

Codex never edits files: the sandbox is read-only and the wrapper only writes under .rnd/cases/<CASE>/reviews/.
Exit: 0 CLEAN, 2 FINDINGS, 3 gate escalation (failed to converge / oscillation), 4 codex error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rndlib  # noqa: E402
import review_gate  # noqa: E402
from rndlib import ROOT, add_history, die, eprint, load_case, now_iso, read_json, rel, save_case, transition, write_json, write_text  # noqa: E402

MAX_DIFF_CHARS = 180_000


# --------------------------------------------------------------------------- #
# Diff
# --------------------------------------------------------------------------- #

# Case management / generated files are never part of a code review diff.
REVIEW_EXCLUDE = [
    ".rnd/index.json", ".rnd/INDEX.md", ".rnd/knowledge/catalog.json",
    ".rnd/cases/*/case.json", ".rnd/cases/*/handoff.md", ".rnd/cases/*/brief.md", ".rnd/cases/*/decision.md",
    ".rnd/cases/*/research/*", ".rnd/cases/*/reports/*", ".rnd/cases/*/reviews/*", ".rnd/cases/*/validation/*",
    ".rnd/cases/*/experiments/*/manifest.json",
    "*/.gitkeep", ".gitkeep",
]


def _excluded(path: str) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, pat.replace("/*", "/**")) for pat in REVIEW_EXCLUDE) \
        or (path.startswith(".rnd/cases/") and any(seg in ("research", "reports", "reviews", "validation") for seg in Path(path).parts[3:4]))


def build_diff(base: str | None, paths: list[str]) -> tuple[str, list[str]]:
    """Return (diff_text, changed_files). Untracked files are appended as full-content pseudo-diffs.
    Case management files (see REVIEW_EXCLUDE) are left out unless --paths names them explicitly."""
    if paths:
        path_args = ["--", *paths]
    else:
        path_args = ["--", ".", *[f":(exclude,glob){pat}" for pat in REVIEW_EXCLUDE]]
    if base:
        r = rndlib.git("diff", "--no-color", base, *path_args)
    else:
        r = rndlib.git("diff", "--no-color", "HEAD", *path_args)
        if r.returncode != 0:  # no HEAD yet (fresh repo)
            r = rndlib.git("diff", "--no-color", "--cached", *path_args)
    if r.returncode != 0:
        die(f"git diff failed: {r.stderr.strip()}")
    diff = r.stdout
    # Ask git for the names separately: `diff --git` headers quote and escape unusual
    # filenames, so parsing them breaks on non-ASCII or spaces.
    name_args = ["diff", "--name-only", "-z"] + ([base] if base else ["HEAD"]) + path_args
    nr = rndlib.git(*name_args)
    files = [f for f in nr.stdout.split("\0") if f] if nr.returncode == 0 else []
    if not base:
        u = [f for f in rndlib.git("ls-files", "--others", "--exclude-standard", "-z", *path_args).stdout.split("\0") if f]
        for f in u:
            p = ROOT / f
            if not p.is_file() or p.stat().st_size > 200_000 or (not paths and _excluded(f)):
                continue
            try:
                body = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            diff += f"\ndiff --git a/{f} b/{f}\nnew file (untracked)\n--- /dev/null\n+++ b/{f}\n" + "".join(f"+{l}\n" for l in body.splitlines())
            files.append(f)
    return diff, files


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #

def build_prompt(case: dict, case_dir: Path, diff: str, files: list[str], pending: list[dict], focus: str | None, tests: list[dict], round_no: int) -> str:
    brief = (case_dir / "brief.md").read_text(encoding="utf-8", errors="ignore") if (case_dir / "brief.md").exists() else ""
    brief = "\n".join(brief.splitlines()[:60])
    pend_txt = "(none)"
    if pending:
        rows = []
        for f in pending:
            note = ""
            for h in reversed(f.get("statusHistory", [])):
                if h.get("by") in ("claude", "lead") and h.get("note"):
                    note = h["note"]
                    break
            rows.append(f"- {f['id']} [{f['status']}] {f['severity']}/{f['category']} {f['file']}:{f.get('line') or '-'} - {f['title']}\n"
                        f"    original: {f['description'][:400]}\n" + (f"    builder's note: {note[:400]}\n" if note else ""))
        pend_txt = "\n".join(rows)
    tests_txt = "\n".join(f"- {t['status']}: {t['name']}" for t in tests) or "(no required tests configured)"
    lang_name = rndlib.language_name(case.get("language", "en"))
    diff_block = diff if len(diff) <= MAX_DIFF_CHARS else diff[:MAX_DIFF_CHARS] + "\n[... diff truncated; run `git --no-pager diff` yourself for the rest ...]\n"
    return f"""You are the INDEPENDENT code reviewer (Codex) for R&D case {case['id']} "{case['title']}" - review round {round_no}.
The code was written by a different agent (Claude Builder). Your job is code correctness only; you must NOT modify any file.
You run in a read-only sandbox in the repository root. You may run read-only commands (git diff, git log, cat, grep, tests are already run for you).

## Case context (from brief.md)
{brief}

## Changed files
{chr(10).join('- ' + f for f in files) or '(none)'}

## Required test results for this round (already executed)
{tests_txt}

## Findings from the previous round that need YOUR verdict
For EVERY id below you must return an entry in `previousFindingsResolution`:
- `confirmed_fixed`  : the fix in the current diff genuinely resolves it
- `still_open`       : not fixed, or fixed incorrectly (explain)
- `false_positive`   : you now agree the finding was wrong (only for `disputed` items, or if you were mistaken)
{pend_txt}

## Review focus
{focus or 'correctness, security, concurrency, error handling, resource leaks, edge cases, test gaps that hide real bugs. Ignore pure style unless it causes a bug.'}

## Rules
- Report only findings you are confident are real, with file and line. Prefer fewer, high-signal findings over speculation.
- `actionable=true` for anything the builder must change before this can pass (blocking/high/medium/low). Use `actionable=false` + severity `info` for optional notes.
- If there are NO actionable findings and all previous findings are resolved, set verdict = "CLEAN".
- Do not suggest re-architecture unless it fixes a real defect.
- Do not modify files. Do not run anything that writes.
- Language: write `summary`, every finding `title`, `description`, `suggestedFix` and every `comment` in **{lang_name}**. Keep file paths, identifiers, code snippets and quoted error text exactly as they appear in the diff. The JSON keys and enum values (verdict, severity, category, resolution) stay as defined by the schema.
- Respond ONLY with JSON matching the provided output schema.

## Diff under review (vs {'base ' + case['review'].get('diffBase') if case['review'].get('diffBase') else 'HEAD + untracked files'})
```diff
{diff_block}
```
"""


# --------------------------------------------------------------------------- #
# Codex invocation
# --------------------------------------------------------------------------- #

def run_codex(prompt: str, out_path: Path, timeout: int, policy: dict) -> tuple[int, str, float]:
    codex = shutil.which("codex")
    if not codex:
        return 127, "codex CLI not found in PATH", 0.0
    schema = rndlib.SCHEMA_DIR / "codex-review-output.schema.json"
    cmd = [
        "timeout", "--kill-after=30", str(timeout),
        codex, "exec", "--skip-git-repo-check", "-C", str(ROOT), "-s", policy["review"].get("codexSandbox", "read-only"),
        "--color", "never", "--output-schema", str(schema), "-o", str(out_path), "-",
    ]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=str(ROOT), timeout=timeout + 60)
        return r.returncode, (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else ""), time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, "codex exec timed out (python-level)", time.time() - t0


def extract_json(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #

def _fp(f: dict) -> str:
    # rndlib.fingerprint is unicode-aware, so Japanese / other non-ASCII titles stay distinct
    return rndlib.fingerprint(f.get("file", ""), f.get("category", ""), f.get("title", ""))


def merge_round(prev: dict | None, codex: dict, round_no: int, ts: str, policy: dict) -> tuple[list[dict], list[str]]:
    """Return (findings for this round, warnings)."""
    warnings: list[str] = []
    unresolved_states = set(policy["review"]["unresolvedStatuses"])
    prev_findings = list(prev.get("findings", [])) if prev else []
    resolutions = {r["id"]: r for r in codex.get("previousFindingsResolution", [])}
    merged: list[dict] = []
    by_fp: dict[str, dict] = {}

    for f in prev_findings:
        nf = json.loads(json.dumps(f))
        if f["status"] in unresolved_states:
            res = resolutions.get(f["id"])
            if res is None:
                warnings.append(f"{f['id']} ({f['status']}) was not addressed by Codex; it stays unresolved")
            elif res["resolution"] == "confirmed_fixed":
                if f["status"] == "disputed":
                    warnings.append(f"{f['id']} was disputed but Codex says confirmed_fixed; treating as confirmed_fixed")
                nf["status"] = "confirmed_fixed"
                nf.setdefault("statusHistory", []).append({"at": ts, "status": "confirmed_fixed", "by": "codex", "note": res.get("comment", "")})
            elif res["resolution"] == "false_positive":
                nf["status"] = "false_positive"
                nf.setdefault("statusHistory", []).append({"at": ts, "status": "false_positive", "by": "codex", "note": res.get("comment", "")})
            elif res["resolution"] == "still_open":
                if f["status"] == "fixed_pending_review":
                    nf["reopenCount"] = f.get("reopenCount", 0) + 1
                nf["status"] = "open"
                nf.setdefault("statusHistory", []).append({"at": ts, "status": "open", "by": "codex", "note": res.get("comment", "")})
                if res.get("comment"):
                    # keep the narrowed residual visible next to the original wording
                    nf["description"] = f"{nf.get('description', '')}\n[round {round_no} residual, per Codex] {res['comment']}"
        merged.append(nf)
        by_fp[nf["fingerprint"]] = nf

    seq = 0
    for raw in codex.get("findings", []):
        fp = _fp(raw)
        existing = by_fp.get(fp)
        if existing is not None:
            if existing["status"] in ("confirmed_fixed",):
                # regression of a finding Codex previously confirmed fixed -> oscillation signal
                existing["status"] = "open"
                existing["reopenCount"] = existing.get("reopenCount", 0) + 1
                existing["description"] = raw.get("description", existing["description"])
                existing["line"] = raw.get("line", existing.get("line"))
                existing.setdefault("statusHistory", []).append({"at": ts, "status": "open", "by": "codex", "note": f"re-reported in round {round_no}"})
                warnings.append(f"{existing['id']} re-appeared after being confirmed fixed (reopenCount={existing['reopenCount']})")
            elif existing["status"] in ("false_positive", "accepted_risk"):
                warnings.append(f"Codex re-reported {existing['id']} which is {existing['status']}; ignored (Lead may revisit)")
            else:
                existing["description"] = raw.get("description", existing["description"])
                existing["line"] = raw.get("line", existing.get("line"))
                existing["severity"] = raw.get("severity", existing["severity"])
                # an item first filed as info can come back as a real defect
                existing["actionable"] = bool(raw.get("actionable", raw.get("severity") != "info"))
                if existing["status"] == "fixed_pending_review":
                    existing["status"] = "open"
                    existing["reopenCount"] = existing.get("reopenCount", 0) + 1
                    existing.setdefault("statusHistory", []).append({"at": ts, "status": "open", "by": "codex", "note": "re-reported as new finding"})
            continue
        seq += 1
        nf = {
            "id": f"F-{round_no:02d}-{seq:03d}",
            "fingerprint": fp,
            "severity": raw.get("severity", "medium"),
            "category": raw.get("category", "other"),
            "file": raw.get("file", "?"),
            "line": raw.get("line") if isinstance(raw.get("line"), int) else None,
            "title": (raw.get("title") or "untitled")[:200],
            "description": raw.get("description", ""),
            "suggestedFix": raw.get("suggestedFix", ""),
            "actionable": bool(raw.get("actionable", raw.get("severity") != "info")),
            "status": "open",
            "firstSeenRound": round_no,
            "reopenCount": 0,
            "statusHistory": [{"at": ts, "status": "open", "by": "codex"}],
        }
        merged.append(nf)
        by_fp[fp] = nf
    return merged, warnings


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("--diff-base")
    ap.add_argument("--paths", nargs="*", default=[])
    ap.add_argument("--timeout", type=int)
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--focus")
    ap.add_argument("--dry-run", action="store_true", help="write prompt + diff, do not call Codex")
    ap.add_argument("--allow-empty", action="store_true")
    a = ap.parse_args(argv)

    policy = rndlib.load_policy()
    try:
        d, c = load_case(a.case)
    except FileNotFoundError as exc:
        die(str(exc))
    rv = c["review"]
    if not rv.get("required"):
        die("review.required is false for this case. `rnd.py review init <CASE>` first (code changes make Codex review mandatory).")
    if rv["status"] in ("failed_to_converge", "oscillation") :
        die(f"review status is {rv['status']}; the Lead must resolve this before another round (no forced PASS).")
    if rv["rounds"] >= rv["maxRounds"]:
        die(f"maxRounds={rv['maxRounds']} already reached -> FAILED_TO_CONVERGE. Lead decision required.")
    if rv.get("convergedAt") and rv["status"] == "converged":
        eprint("note: review already converged; a new round re-opens it (code changed after convergence).")
        rv["status"] = "in_progress"

    base = a.diff_base if a.diff_base is not None else rv.get("diffBase")
    if a.diff_base is not None:
        rv["diffBase"] = a.diff_base or None
    diff, files = build_diff(base or None, a.paths)
    if not diff.strip() and not a.allow_empty:
        die("nothing to review: the diff is empty (commit/base mismatch? use --diff-base or --allow-empty)")
    diff_hash = rndlib.sha256_text(diff)

    round_no = rv["rounds"] + 1
    rdir = d / "reviews" / f"round-{round_no:02d}"
    rdir.mkdir(parents=True, exist_ok=True)
    ts = now_iso()
    write_text(rdir / "diff.patch", diff)

    # 1. tests -> codex
    tests: list[dict] = []
    if rv.get("requiredTests") and not a.skip_tests:
        from rnd import run_required_tests  # local import to keep rnd.py the single implementation
        tests = run_required_tests(d, c)
    write_json(rdir / "tests.json", {"caseId": c["id"], "round": round_no, "at": ts, "skipped": a.skip_tests, "results": tests})
    for t in tests:
        print(f"test {t['status']}: {t['name']}")

    prev = rndlib.latest_findings(d)
    prev_fj = prev[2] if prev else None
    pending = rndlib.unresolved_findings(prev_fj, policy) if prev_fj else []
    prompt = build_prompt(c, d, diff, files, pending, a.focus, tests, round_no)
    write_text(rdir / "prompt.md", prompt)
    meta = {"caseId": c["id"], "round": round_no, "startedAt": ts, "diffBase": base or None, "diffHash": diff_hash,
            "files": files, "pendingFromPrevious": [f["id"] for f in pending], "head": rndlib.git_head(), "dryRun": a.dry_run}

    if a.dry_run:
        write_json(rdir / "meta.json", meta)
        print(f"dry-run: prompt written to {rel(rdir / 'prompt.md')} ({len(prompt)} chars, {len(files)} files). No case.json change.")
        return 0

    timeout = min(a.timeout or policy["review"]["codexTimeoutSec"], policy["review"]["codexMaxTimeoutSec"])
    last_msg = rdir / "codex_last_message.json"
    code, output, elapsed = run_codex(prompt, last_msg, timeout, policy)
    write_text(rdir / "codex_output.md", f"# codex exec output (exit {code}, {elapsed:.0f}s)\n\n```\n{output}\n```\n")
    meta.update({"codexExit": code, "elapsedSec": round(elapsed, 1), "finishedAt": now_iso(), "timeoutSec": timeout})
    ver = subprocess.run(["codex", "--version"], capture_output=True, text=True).stdout.strip() if shutil.which("codex") else "codex (missing)"

    parsed = None
    if last_msg.exists():
        parsed = extract_json(last_msg.read_text(encoding="utf-8", errors="ignore"))
    if parsed is None:
        parsed = extract_json(output)
    if code == 124 or code == 137:
        meta["reason"] = "timeout"
    if parsed is None or "findings" not in parsed:
        fj = {"schemaVersion": 1, "caseId": c["id"], "round": round_no, "reviewer": ver, "verdict": "ERROR", "reviewedAt": now_iso(),
              "diffBase": base or None, "diffHash": diff_hash, "summary": f"codex exec failed or returned no parsable JSON (exit {code})",
              "rawOutput": "codex_output.md", "previousFindingsResolution": [],
              "findings": prev_fj["findings"] if prev_fj else []}
        write_json(rdir / "findings.json", fj)
        write_json(rdir / "meta.json", meta)
        rv["rounds"] = round_no
        rv["lastRoundVerdict"] = "ERROR"
        rv["consecutiveClean"] = 0   # an unusable round breaks the CLEAN streak
        rv["status"] = "in_progress"
        add_history(c, "review.round", by="codex", note=f"round {round_no}: ERROR (exit {code})")
        save_case(d, c, action_by="codex-reviewer", action=f"review round {round_no}: ERROR")
        eprint(f"Codex round {round_no} ERROR (exit {code}). See {rel(rdir / 'codex_output.md')}. "
               f"{'Do not retry the same prompt on timeout; shorten the diff (--paths) or report to the Lead.' if meta.get('reason') == 'timeout' else ''}")
        return 4

    findings, warnings = merge_round(prev_fj, parsed, round_no, ts, policy)
    unresolved = [f for f in findings if f.get("actionable", True) and f["status"] in policy["review"]["unresolvedStatuses"]]
    verdict = "CLEAN" if not unresolved else "FINDINGS"
    if parsed.get("verdict") == "CLEAN" and unresolved:
        warnings.append("Codex said CLEAN but unresolved findings remain (unaddressed previous items) -> FINDINGS")
    fj = {"schemaVersion": 1, "caseId": c["id"], "round": round_no, "reviewer": ver, "verdict": verdict, "reviewedAt": now_iso(),
          "diffBase": base or None, "diffHash": diff_hash, "summary": parsed.get("summary", ""), "rawOutput": "codex_output.md",
          "previousFindingsResolution": [{"id": r["id"], "resolution": r["resolution"], "comment": r.get("comment", "")}
                                          for r in parsed.get("previousFindingsResolution", []) if r.get("resolution") in ("confirmed_fixed", "still_open", "false_positive", "accepted_risk")],
          "findings": findings}
    errs = rndlib.validate("findings", fj)
    if errs:
        eprint("warning: findings.json failed schema validation: " + "; ".join(errs[:5]))
    write_json(rdir / "findings.json", fj)
    meta["warnings"] = warnings
    write_json(rdir / "meta.json", meta)

    rv["rounds"] = round_no
    rv["lastRoundVerdict"] = verdict
    rv["consecutiveClean"] = rv.get("consecutiveClean", 0) + 1 if verdict == "CLEAN" else 0
    rv["status"] = "in_progress"
    if c["state"] in ("BUILDING", "EXPERIMENTING", "VALIDATING"):
        transition(c, "REVIEWING", by="codex-reviewer", note=f"round {round_no}", force=True)
    add_history(c, "review.round", by="codex", note=f"round {round_no}: {verdict}, {len(unresolved)} unresolved")
    save_case(d, c, action_by="codex-reviewer", action=f"review round {round_no}: {verdict}")

    gate = review_gate.evaluate(d, c, policy)
    review_gate.apply(d, c, gate)
    subprocess.call([sys.executable, str(rndlib.SCRIPTS_DIR / "rnd.py"), "handoff", c["id"]], stdout=subprocess.DEVNULL)

    print(f"\nCodex round {round_no}: {verdict}  ({elapsed:.0f}s)  -> {rel(rdir)}")
    if parsed.get("summary"):
        print(f"summary: {parsed['summary'][:500]}")
    for f in findings:
        if f["status"] in policy["review"]["unresolvedStatuses"] or f.get("firstSeenRound") == round_no or f["id"] in [r["id"] for r in fj["previousFindingsResolution"]]:
            print(f"  {f['id']} [{f['status']}] {f['severity']}/{f['category']} {f['file']}:{f.get('line') or '-'}  {f['title']}")
    for w in warnings:
        print(f"  ! {w}")
    print(f"gate: {gate['verdict']}" + (" - " + "; ".join(gate["reasons"]) if gate["reasons"] else ""))
    if gate["verdict"] in ("FAILED_TO_CONVERGE", "REVIEW_OSCILLATION"):
        return 3
    return 0 if verdict == "CLEAN" and gate["verdict"] == "CONVERGED" else 2


if __name__ == "__main__":
    sys.exit(main())
