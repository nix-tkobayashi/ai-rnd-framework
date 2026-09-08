#!/usr/bin/env python3
"""review_gate.py - Codex review convergence gate (SPEC §22-§25).

  python3 .claude/scripts/review_gate.py <CASE> [--json] [--apply]

Verdicts (exit code):
  CONVERGED           0   actionable findings = 0 AND required tests PASS AND (high risk: 2 consecutive CLEAN)
  NOT_CONVERGED       2   another round is needed (reasons listed)
  FAILED_TO_CONVERGE  3   maxRounds reached without convergence
  REVIEW_OSCILLATION  3   the same finding re-opened >= threshold times
  NOT_REQUIRED        0   review not required for this case
  NO_ROUNDS           2   review required but no round yet

The gate never changes a finding's status; it only reads the round files.
--apply writes the resulting review.status / case state to case.json (the Lead's call).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rndlib  # noqa: E402
from rndlib import load_case, now_iso, read_json, save_case, transition  # noqa: E402


def evaluate(case_dir: Path, case: dict, policy: dict | None = None) -> dict:
    policy = policy or rndlib.load_policy()
    rv = case["review"]
    out: dict = {"caseId": case["id"], "verdict": None, "reasons": [], "rounds": rv["rounds"], "maxRounds": rv["maxRounds"],
                 "consecutiveClean": rv.get("consecutiveClean", 0), "requiredCleanRounds": rv.get("requiredCleanRounds", 1),
                 "unresolved": [], "tests": [], "oscillating": []}
    if not rv.get("required"):
        out["verdict"] = "NOT_REQUIRED"
        return out
    rounds = rndlib.load_findings_rounds(case_dir)
    if not rounds:
        out["verdict"] = "NO_ROUNDS"
        out["reasons"].append("no Codex review round recorded (run .claude/scripts/codex_review.py)")
        return out
    n, rd, fj = rounds[-1]
    out["latestRound"] = n
    out["latestVerdict"] = fj["verdict"]
    threshold = policy["review"]["oscillationReopenThreshold"]
    for f in fj["findings"]:
        if f.get("reopenCount", 0) >= threshold and f["status"] in policy["review"]["unresolvedStatuses"]:
            out["oscillating"].append({"id": f["id"], "fingerprint": f["fingerprint"], "reopenCount": f["reopenCount"], "title": f["title"]})
    if out["oscillating"]:
        out["verdict"] = "REVIEW_OSCILLATION"
        out["reasons"].append(f"{len(out['oscillating'])} finding(s) keep re-appearing after fixes -> escalate to Lead")
        return out
    unresolved = rndlib.unresolved_findings(fj, policy)
    out["unresolved"] = [{"id": f["id"], "status": f["status"], "severity": f["severity"], "title": f["title"]} for f in unresolved]
    if fj["verdict"] == "ERROR":
        out["reasons"].append("latest round ended in ERROR (Codex did not return a usable review)")
    if unresolved:
        out["reasons"].append(f"{len(unresolved)} actionable finding(s) unresolved (open / fixed_pending_review / disputed)")
    tests = read_json(rd / "tests.json", {"results": []}).get("results", [])
    out["tests"] = [{"name": t["name"], "status": t["status"]} for t in tests]
    if rv.get("requiredTests"):
        if not tests:
            out["reasons"].append("required tests were not run for the latest round")
        elif any(t["status"] != "PASS" for t in tests):
            out["reasons"].append("required tests FAIL in the latest round")
    consecutive = rv.get("consecutiveClean", 0)
    need = rv.get("requiredCleanRounds", 1)
    # A case converges only on Codex's own CLEAN verdict. Clearing the last finding by any
    # other route (accepted_risk, false_positive) still needs a confirming round, so the
    # count is checked whatever the latest verdict was.
    if consecutive < need:
        out["reasons"].append(
            f"needs {need} consecutive CLEAN round(s) from Codex, have {consecutive}"
            + (f" (latest verdict {fj['verdict']})" if fj["verdict"] != "CLEAN" else ""))
    if not out["reasons"]:
        out["verdict"] = "CONVERGED"
    elif rv["rounds"] >= rv["maxRounds"]:
        out["verdict"] = "FAILED_TO_CONVERGE"
        out["reasons"].append(f"maxRounds={rv['maxRounds']} reached; forced PASS is forbidden -> back to Lead")
    else:
        out["verdict"] = "NOT_CONVERGED"
    return out


def apply(case_dir: Path, case: dict, result: dict) -> None:
    rv = case["review"]
    v = result["verdict"]
    if v == "CONVERGED":
        rv["status"] = "converged"
        rv["convergedAt"] = rv.get("convergedAt") or now_iso()
        case["nextAction"] = "Dispatch Validator (acceptance criteria / reproducibility), then Decision"
    elif v == "FAILED_TO_CONVERGE":
        rv["status"] = "failed_to_converge"
        if case["state"] != "FAILED_TO_CONVERGE":
            transition(case, "FAILED_TO_CONVERGE", by="review-gate", note="; ".join(result["reasons"]))
        case["nextAction"] = "Lead decision: redesign / split the change / record inconclusive. Do NOT force PASS."
    elif v == "REVIEW_OSCILLATION":
        rv["status"] = "oscillation"
        if case["state"] != "BLOCKED":
            transition(case, "BLOCKED", by="review-gate", note="REVIEW_OSCILLATION: " + ", ".join(o["id"] for o in result["oscillating"]))
        case["nextAction"] = "REVIEW_OSCILLATION - Lead must arbitrate the oscillating findings before another round"
    elif v == "NOT_CONVERGED":
        rv["status"] = "in_progress"
        case["nextAction"] = "Fix unresolved findings (finding set ... fixed_pending_review), run tests, then next Codex round"
    save_case(case_dir, case, action_by="review-gate", action=f"review gate: {v}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    try:
        d, c = load_case(a.case)
    except FileNotFoundError as exc:
        rndlib.die(str(exc))
    res = evaluate(d, c)
    if a.apply and res["verdict"] not in ("NOT_REQUIRED", "NO_ROUNDS"):
        apply(d, c, res)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"{res['caseId']} review gate: {res['verdict']}  (round {res['rounds']}/{res['maxRounds']}, consecutiveClean {res['consecutiveClean']}/{res['requiredCleanRounds']})")
        for r in res["reasons"]:
            print(f"  - {r}")
        for u in res["unresolved"]:
            print(f"    {u['id']} [{u['status']}] {u['severity']}: {u['title']}")
        for o in res["oscillating"]:
            print(f"    OSCILLATING {o['id']} reopened x{o['reopenCount']}: {o['title']}")
        for t in res["tests"]:
            print(f"    test {t['status']}: {t['name']}")
    return {"CONVERGED": 0, "NOT_REQUIRED": 0, "NOT_CONVERGED": 2, "NO_ROUNDS": 2}.get(res["verdict"], 3)


if __name__ == "__main__":
    sys.exit(main())
