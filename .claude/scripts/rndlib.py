#!/usr/bin/env python3
"""Shared helpers for the ai-rnd-workspace scripts.

Everything that touches the Single Source of Truth (.rnd/cases/<CASE>/case.json and
friends) goes through this module so that the file formats stay consistent
between rnd.py, codex_review.py, review_gate.py, generate_index.py and the
hooks.

No third-party dependencies are required. If `jsonschema` is importable it is
used for validation; otherwise a small built-in validator (type / required /
enum / pattern / properties / items / const / additionalProperties) is used.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def find_root(start: Path | None = None) -> Path:
    """Locate the workspace root (directory containing .claude/rnd-policy.json)."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and (Path(env) / ".claude" / "rnd-policy.json").exists():
        return Path(env).resolve()
    here = (start or Path(__file__).resolve().parent)
    for cand in [here, *here.parents]:
        if (cand / ".claude" / "rnd-policy.json").exists():
            return cand
    return Path.cwd().resolve()


ROOT = find_root()
POLICY_PATH = ROOT / ".claude" / "rnd-policy.json"

# Where the engine and the R&D data live. Both are dot-directories so the engine
# can sit inside any repository next to that repository's own files; change
# `layout` in .claude/rnd-policy.json rather than these defaults.
DEFAULT_LAYOUT = {
    "engineDir": ".claude",
    "scriptsDir": ".claude/scripts",
    "schemasDir": ".claude/schemas",
    "testsDir": ".claude/tests",
    "dataDir": ".rnd",
    "casesDir": ".rnd/cases",
    "knowledgeDir": ".rnd/knowledge",
}


def _load_layout() -> dict:
    layout = dict(DEFAULT_LAYOUT)
    try:
        with open(POLICY_PATH, encoding="utf-8") as f:
            layout.update(json.load(f).get("layout", {}) or {})
    except (OSError, ValueError):
        pass
    return layout


LAYOUT = _load_layout()
ENGINE_DIR = ROOT / LAYOUT["engineDir"]
SCRIPTS_DIR = ROOT / LAYOUT["scriptsDir"]
SCHEMA_DIR = ROOT / LAYOUT["schemasDir"]
TESTS_DIR = ROOT / LAYOUT["testsDir"]
RND_ROOT = ROOT / LAYOUT["dataDir"]
RND_DIR = ROOT / LAYOUT["casesDir"]
KNOWLEDGE_DIR = ROOT / LAYOUT["knowledgeDir"]

VERSION_FILE = ENGINE_DIR / "VERSION"

# Files the engine generates on demand; a host repository should git-ignore them.
GENERATED_FILES = [f"{LAYOUT['dataDir']}/index.json", f"{LAYOUT['dataDir']}/INDEX.md", f"{LAYOUT['knowledgeDir']}/catalog.json"]
# What `rnd.py install` adds to a host's .gitignore: the generated files plus the Python caches
# the hooks and the engine tests leave under the engine directory.
HOST_IGNORE_LINES = GENERATED_FILES + [f"{LAYOUT['engineDir']}/**/__pycache__/", f"{LAYOUT['engineDir']}/.pytest_cache/"]
# Sample paths `rnd_doctor.py` asks git about to see that those lines are in effect.
HOST_IGNORE_PROBES = GENERATED_FILES + [f"{LAYOUT['scriptsDir']}/__pycache__/rndlib.cpython-312.pyc", f"{LAYOUT['engineDir']}/.pytest_cache/v/cache/nodeids"]
# Not part of the engine even when present in a source checkout.
ENGINE_CACHE_PATTERNS = ("__pycache__", "*.py[cod]", ".pytest_cache")

# Everything `rnd.py install` copies into a host repository, relative to the engine
# directory. `settings.json` is merged, not copied, so it is listed separately.
ENGINE_ITEMS = ["VERSION", "rnd-policy.json", "pytest.ini", "agents", "skills", "hooks", "rules", "scripts", "schemas", "tests"]
ENGINE_SETTINGS = "settings.json"


def engine_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


# Output-language support. Research is done in the sources' languages; reports,
# synthesis, decision and Codex finding texts are written in the case language.
LANGUAGES = {"en": "English", "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "de": "German", "fr": "French", "es": "Spanish"}


def detect_language(text: str) -> str:
    """Best-effort language code from a question/title. Japanese/Chinese/Korean by script; otherwise 'en'."""
    if re.search(r"[\u3040-\u30ff]", text):  # hiragana / katakana
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):  # hangul
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):  # CJK ideographs without kana -> Chinese
        return "zh"
    return "en"


def language_name(code: str) -> str:
    return LANGUAGES.get(code, code)


CASE_ID_RE = re.compile(r"^RND-\d{8}-\d{3}$")
EXP_ID_RE = re.compile(r"^EXP-\d{3}$")

STATES = [
    "NEW", "TRIAGE", "RESEARCHING", "DESIGNING", "EXPERIMENTING", "BUILDING",
    "REVIEWING", "VALIDATING", "DECIDED", "ARCHIVED",
]
EXCEPTION_STATES = ["BLOCKED", "FAILED", "FAILED_TO_CONVERGE", "INCONCLUSIVE", "STALE"]
ALL_STATES = STATES + EXCEPTION_STATES

# Forward transitions allowed without --force. Any state may go to an
# exception state; exception states may return to the state they left.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"TRIAGE", "RESEARCHING"},
    "TRIAGE": {"RESEARCHING", "DESIGNING", "BUILDING"},
    "RESEARCHING": {"DESIGNING", "BUILDING", "DECIDED", "RESEARCHING"},
    "DESIGNING": {"EXPERIMENTING", "BUILDING", "RESEARCHING"},
    "EXPERIMENTING": {"BUILDING", "REVIEWING", "VALIDATING", "DESIGNING", "DECIDED"},
    "BUILDING": {"REVIEWING", "EXPERIMENTING"},
    "REVIEWING": {"VALIDATING", "BUILDING"},
    "VALIDATING": {"DECIDED", "BUILDING", "REVIEWING"},
    "DECIDED": {"ARCHIVED", "RESEARCHING"},
    "ARCHIVED": {"RESEARCHING"},
    "BLOCKED": set(STATES),
    "FAILED": {"RESEARCHING", "DESIGNING", "BUILDING", "DECIDED", "ARCHIVED"},
    "FAILED_TO_CONVERGE": {"BUILDING", "DECIDED", "ARCHIVED"},
    "INCONCLUSIVE": {"RESEARCHING", "DESIGNING", "DECIDED", "ARCHIVED"},
    "STALE": {"RESEARCHING", "ARCHIVED"},
}

FINDING_STATUSES = ["open", "fixed_pending_review", "confirmed_fixed", "disputed", "false_positive", "accepted_risk"]


# --------------------------------------------------------------------------- #
# Time / ids
# --------------------------------------------------------------------------- #

def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_compact() -> str:
    return _dt.datetime.now().strftime("%Y%m%d")


def parse_iso(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def slugify(text: str, max_len: int = 60) -> str:
    """Directory-safe slug that keeps non-ASCII letters (Japanese titles must not
    collapse to 'case'). Only path-hostile characters and separators are replaced."""
    s = unicodedata.normalize("NFC", text).lower()
    s = re.sub(r"[^\w]+", "-", s, flags=re.UNICODE).strip("-")
    s = re.sub(r"_+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    if not s:
        s = "case"
    return s[:max_len].strip("-")


def next_case_id(date: str | None = None) -> str:
    date = date or today_compact()
    RND_DIR.mkdir(parents=True, exist_ok=True)
    seq = 0
    for d in RND_DIR.iterdir():
        m = re.match(rf"^RND-{date}-(\d{{3}})", d.name)
        if m:
            seq = max(seq, int(m.group(1)))
    return f"RND-{date}-{seq + 1:03d}"


def fingerprint(*parts: str) -> str:
    # unicode-aware: keep letters/digits of any script so non-English titles stay distinct
    norm = "|".join(re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (p or "").strip().lower())) for p in parts)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


# --------------------------------------------------------------------------- #
# JSON IO
# --------------------------------------------------------------------------- #

def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def write_text(path: Path, text: str, overwrite: bool = True) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def load_policy() -> dict:
    return read_json(POLICY_PATH)


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #

def _builtin_validate(schema: dict, data: Any, path: str = "$", root: dict | None = None) -> list[str]:
    root = root or schema
    errors: list[str] = []
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.startswith("#/"):
            node: Any = root
            for part in ref[2:].split("/"):
                node = node[part]
            return _builtin_validate(node, data, path, root)
    if "const" in schema and data != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: {data!r} not in enum {schema['enum']}")
    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        ok = False
        for ty in types:
            if ty == "object" and isinstance(data, dict):
                ok = True
            elif ty == "array" and isinstance(data, list):
                ok = True
            elif ty == "string" and isinstance(data, str):
                ok = True
            elif ty == "integer" and isinstance(data, int) and not isinstance(data, bool):
                ok = True
            elif ty == "number" and isinstance(data, (int, float)) and not isinstance(data, bool):
                ok = True
            elif ty == "boolean" and isinstance(data, bool):
                ok = True
            elif ty == "null" and data is None:
                ok = True
        if not ok:
            errors.append(f"{path}: type {type(data).__name__} not in {types}")
            return errors
    if isinstance(data, str):
        if "pattern" in schema and not re.search(schema["pattern"], data):
            errors.append(f"{path}: {data!r} does not match {schema['pattern']}")
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{path}: {data} < minimum {schema['minimum']}")
    if isinstance(data, dict):
        for req in schema.get("required", []):
            if req not in data:
                errors.append(f"{path}: missing required '{req}'")
        props = schema.get("properties", {})
        for k, v in data.items():
            if k in props:
                errors.extend(_builtin_validate(props[k], v, f"{path}.{k}", root))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property '{k}'")
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, item in enumerate(data):
                errors.extend(_builtin_validate(schema["items"], item, f"{path}[{i}]", root))
        if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in data}) != len(data):
            errors.append(f"{path}: items are not unique")
    return errors


def validate(schema_name: str, data: Any) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    schema = read_json(SCHEMA_DIR / f"{schema_name}.schema.json")
    try:
        import jsonschema  # type: ignore
        validator = jsonschema.Draft202012Validator(schema)
        return [f"{'/'.join(str(p) for p in e.absolute_path) or '$'}: {e.message}" for e in validator.iter_errors(data)]
    except ImportError:
        return _builtin_validate(schema, data)


# --------------------------------------------------------------------------- #
# Cases
# --------------------------------------------------------------------------- #

def case_dirs() -> list[Path]:
    if not RND_DIR.exists():
        return []
    return sorted(p for p in RND_DIR.iterdir() if p.is_dir() and re.match(r"^RND-\d{8}-\d{3}(-|$)", p.name))


def resolve_case_dir(case_ref: str) -> Path:
    """Accept a case id (RND-YYYYMMDD-NNN), a full directory name, or a path."""
    p = Path(case_ref)
    if p.is_dir() and (p / "case.json").exists():
        return p.resolve()
    for d in case_dirs():
        if d.name == case_ref or d.name.startswith(case_ref + "-") or d.name == case_ref:
            return d
    raise FileNotFoundError(f"Case not found: {case_ref}")


def load_case(case_ref: str) -> tuple[Path, dict]:
    d = resolve_case_dir(case_ref)
    return d, read_json(d / "case.json")


def save_case(case_dir: Path, case: dict, action_by: str = "lead", action: str | None = None, validate_schema: bool = True) -> None:
    case["updated"] = now_iso()
    if action:
        case["lastAction"] = {"at": case["updated"], "by": action_by, "summary": action}
    if validate_schema:
        errs = validate("case", case)
        if errs:
            raise ValueError("case.json would be invalid:\n  " + "\n  ".join(errs))
    write_json(case_dir / "case.json", case)


def add_history(case: dict, event: str, by: str = "lead", frm: str | None = None, to: str | None = None, note: str = "") -> None:
    entry: dict[str, Any] = {"at": now_iso(), "event": event, "by": by}
    if frm is not None:
        entry["from"] = frm
    if to is not None:
        entry["to"] = to
    if note:
        entry["note"] = note
    case.setdefault("history", []).append(entry)


def transition(case: dict, to: str, by: str = "lead", note: str = "", force: bool = False) -> None:
    frm = case["state"]
    if to not in ALL_STATES:
        raise ValueError(f"Unknown state {to}")
    if not force and frm != to:
        allowed = ALLOWED_TRANSITIONS.get(frm, set())
        if to not in allowed and to not in EXCEPTION_STATES:
            raise ValueError(f"Transition {frm} -> {to} is not allowed (use --force with a note to override)")
    case["state"] = to
    add_history(case, "state", by=by, frm=frm, to=to, note=note)


def load_findings_rounds(case_dir: Path) -> list[tuple[int, Path, dict]]:
    """Return [(round_no, round_dir, findings_json)] sorted by round."""
    out = []
    rdir = case_dir / "reviews"
    if not rdir.exists():
        return out
    for d in sorted(rdir.iterdir()):
        m = re.match(r"^round-(\d{2,})$", d.name)
        if m and (d / "findings.json").exists():
            out.append((int(m.group(1)), d, read_json(d / "findings.json")))
    return out


def latest_findings(case_dir: Path) -> tuple[int, Path, dict] | None:
    rounds = load_findings_rounds(case_dir)
    return rounds[-1] if rounds else None


def unresolved_findings(findings: dict, policy: dict | None = None) -> list[dict]:
    policy = policy or load_policy()
    unresolved = set(policy["review"]["unresolvedStatuses"])
    return [f for f in findings.get("findings", []) if f.get("actionable", True) and f.get("status") in unresolved]


# --------------------------------------------------------------------------- #
# Git helpers
# --------------------------------------------------------------------------- #

def git(*args: str, cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd or ROOT), capture_output=True, text=True, check=check)


def git_head(cwd: Path | None = None) -> str | None:
    r = git("rev-parse", "HEAD", cwd=cwd)
    return r.stdout.strip() if r.returncode == 0 else None


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #

def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def eprint(*a: Any, **kw: Any) -> None:
    print(*a, file=sys.stderr, **kw)


def die(msg: str, code: int = 1) -> None:
    eprint(f"error: {msg}")
    sys.exit(code)


def freshness_class_for(text: str, policy: dict | None = None) -> str:
    policy = policy or load_policy()
    low = text.lower()
    for hint in policy["freshness"]["fastMovingHints"]:
        if hint in low:
            return "fast-moving"
    return "normal"


def evidence_is_stale(ev: dict, policy: dict | None = None, now: _dt.datetime | None = None) -> bool:
    policy = policy or load_policy()
    now = now or _dt.datetime.now(_dt.timezone.utc)
    max_days = policy["freshness"]["maxAgeDays"].get(ev.get("freshnessClass", "normal"), 180)
    ref = parse_iso(ev.get("lastVerified")) or parse_iso(ev.get("retrievedAt"))
    if ref is None:
        return True
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=_dt.timezone.utc)
    return (now - ref).days > max_days


def iter_case_text_files(case_dir: Path) -> Iterable[Path]:
    for p in case_dir.rglob("*"):
        if p.is_file() and p.suffix in {".md", ".json", ".txt", ".log"} and "artifacts" not in p.parts:
            yield p
