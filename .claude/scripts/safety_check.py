#!/usr/bin/env python3
"""Safety checks shared by the hooks and usable from the CLI.

Usage:
  python3 .claude/scripts/safety_check.py command "<shell command>" [--agent NAME]
  python3 .claude/scripts/safety_check.py path <path> --agent builder [--case RND-...]
  python3 .claude/scripts/safety_check.py secrets <file-or-dir>...
  python3 .claude/scripts/safety_check.py diff [<git ref>]      # scan a diff for secrets / protected paths

Exit code 0 = allowed / clean, 2 = denied / findings, 1 = usage error.

The functions here are pure (policy in, verdict out) so the hooks in
.claude/hooks/ can import them and tests can exercise them directly.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rndlib  # noqa: E402

BUILDER_AGENTS = {"builder", "isolated-builder"}
REVIEWER_AGENTS = {"codex-reviewer"}
VALIDATOR_AGENTS = {"validator"}
READONLY_AGENTS = {"researcher", "critic", "claim-verifier", "experiment-designer", "codex-reviewer"}

# Directories where every agent (incl. builders) may create scratch files.
TEMP_PREFIXES = ("/tmp/", "/var/tmp/", "/dev/shm/")

# Interpreters: a heredoc fed to one of these is executed, not stored -> keep it for scanning.
_INTERPRETER_RE = re.compile(r"(^|[\s;&|(])(ba|z|da)?sh\b|\bpython3?\b|\bperl\b|\bnode\b|\bruby\b|\beval\b|\bsource\b|\bxargs\b")
_HEREDOC_RE = re.compile(r"(?P<line>[^\n]*<<-?\s*(?P<q>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=q)[^\n]*)\n(?P<body>.*?)\n[ \t]*(?P=tag)[ \t]*(?=\n|$)", re.S)

# Commands whose (non-option) arguments are written to / deleted.
_WRITE_CMDS = {"rm", "mv", "cp", "mkdir", "touch", "chmod", "chown", "ln", "truncate", "patch", "tee", "install", "unzip", "rmdir", "shred"}
_WRITE_CMD_RE = re.compile(r"(^|[\s;&|(])(?:sudo\s+)?(" + "|".join(sorted(_WRITE_CMDS)) + r")\s+((?:[^\s;&|]+\s*)+)")
_SED_INPLACE_RE = re.compile(r"(^|[\s;&|(])(sed|perl)\s+(-[A-Za-z]*i[A-Za-z]*\S*\s+)((?:[^\s;&|]+\s*)+)")
_REDIRECT_RE = re.compile(r"(?<![<>0-9])[12]?>>?\s*(?!&)([^\s;&|)]+)")
_GIT_WRITE_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(add|commit|checkout|switch|restore|stash|merge|rebase|reset|apply|rm|mv|clean|worktree\s+add)\b")


_SUBST_RE = re.compile(r"\$\((?P<paren>[^()]*(?:\([^()]*\)[^()]*)*)\)|`(?P<tick>[^`]*)`", re.S)


def _substitutions(text: str) -> str:
    """Command substitutions inside `text`, joined - they execute even inside double quotes.
    Backslash-escaped forms (\\$(...) in a heredoc body) are inert and are skipped."""
    out = []
    for m in _SUBST_RE.finditer(text):
        if m.start() > 0 and text[m.start() - 1] == "\\":
            continue
        out.append(m.group("paren") or m.group("tick") or "")
    return " ; ".join(out)


def strip_heredocs(cmd: str) -> str:
    """Remove heredoc bodies that are *data* (cat > file <<EOF ...). A body is kept when it
    will actually run: piped into or fed to an interpreter, or an unquoted delimiter (which
    makes the shell expand $(...) and `...` inside the body)."""
    def repl(m: re.Match) -> str:
        line, tag, body = m.group("line"), m.group("tag"), m.group("body")
        after_op = line.split("<<", 1)[1] if "<<" in line else ""
        if _INTERPRETER_RE.search(line.split("<<", 1)[0]) or _INTERPRETER_RE.search(after_op):
            return m.group(0)                      # bash <<EOF ... / cat <<EOF | bash
        if not m.group("q"):                       # unquoted delimiter -> body is expanded
            return line + "\n" + _substitutions(body) + "\n" + tag
        return line + "\n" + tag
    return _HEREDOC_RE.sub(repl, cmd)


_SEGMENT_SPLIT_RE = re.compile(r"\|\||&&|;|\n|\||&")
_CD_RE = re.compile(r"^(?:cd|pushd)\s+(?P<dir>[^\s;&|]+)\s*$")
# interpreter one-liners that write: python -c "...open(p,'w')...", node -e, perl -e
_INTERP_WRITE_RE = re.compile(
    # open(path, "w") / io.open(path, mode="a") - a bare open() is a read and is fine
    r"""(?:\bio\.)?\bopen\s*\(\s*["'](?P<open>[^"']+)["']\s*,\s*(?:mode\s*=\s*)?["'][wax+]"""
    # Path("p").write_text(...) / .unlink() / .mkdir() ...
    r"""|\b(?:Path|PurePath)\s*\(\s*["'](?P<path>[^"']+)["']\s*\)\s*(?:\.\s*\w+\s*\([^)]*\)\s*)*"""
    r"""\.\s*(?:write_text|write_bytes|writelines|unlink|mkdir|touch|rename|replace|chmod|rmdir|symlink_to|hardlink_to)\s*\("""
    # os.remove("p") / shutil.rmtree("p") / os.makedirs("p")
    r"""|\bos\s*\.\s*(?:remove|unlink|rmdir|removedirs|rename|replace|mkdir|makedirs|chmod|chown|truncate)\s*\(\s*["'](?P<os>[^"']+)["']"""
    r"""|\bshutil\s*\.\s*(?:rmtree|move|copy|copy2|copyfile|copytree)\s*\(\s*["'](?P<sh>[^"']+)["']""",
)


def _dequote(tok: str) -> str:
    """Remove shell quoting from a single word: .clau\"de\"/x -> .claude/x."""
    return re.sub(r"[\"'\\]", "", tok)


def _segment_targets(seg: str) -> list[str]:
    out: list[str] = []
    for m in _REDIRECT_RE.finditer(seg):
        out.append(m.group(1))
    for m in _WRITE_CMD_RE.finditer(seg):
        out.extend(t for t in m.group(3).split() if not t.startswith("-"))
    for m in _SED_INPLACE_RE.finditer(seg):
        out.extend([t for t in m.group(4).split() if not t.startswith("-")][1:])
    for m in _INTERP_WRITE_RE.finditer(seg):
        out.extend(g for g in (m.group("open"), m.group("path"), m.group("os"), m.group("sh")) if g)
    if _GIT_WRITE_RE.search(seg):
        out.append(".git/")
    return out


def write_targets(cmd: str, cwd: str | None = None) -> list[str]:
    """Paths a shell command would create/modify/delete: redirect targets, arguments of
    write commands (rm/mv/cp/mkdir/touch/chmod/...), sed/perl -i files, interpreter
    one-liner writes, and git write operations. Reads are ignored.

    `cd` is followed so `cd .claude && touch x` resolves to `.claude/x`, but every directory
    seen (including the one the command started in) stays a candidate: a `cd` in a pipeline or
    a `cd -` cannot move a relative write out of a protected directory.
    """
    unq = strip_heredocs(cmd)
    unq += " ; " + _substitutions(unq)          # command substitutions execute too
    bases: list[str] = [cwd or ""]
    targets: list[str] = []
    for seg in _SEGMENT_SPLIT_RE.split(unq):
        seg = seg.strip()
        if not seg:
            continue
        cd = _CD_RE.match(seg)
        if cd:
            d = _dequote(cd.group("dir"))
            if d in ("-", "~", "$HOME", "$OLDPWD"):
                continue                        # cannot resolve: keep the bases we have
            nxt = d if os.path.isabs(d) else os.path.normpath(os.path.join(bases[-1] or ".", d))
            if nxt not in bases:
                bases.append(nxt)
            continue
        for t in _segment_targets(seg):
            t = _dequote(t)
            if not t or t in {"/dev/null", "/dev/stdout", "/dev/stderr", "&1", "&2"} or t.startswith("-"):
                continue
            if os.path.isabs(t):
                targets.append(t)
                continue
            for b in bases:
                targets.append(os.path.normpath(os.path.join(b, t)) if b else t)
    return targets


WRITE_INDICATORS = [
    r"(^|[^<>])>\s*\S", r">>", r"\btee\b", r"\bsed\s+-[a-zA-Z]*i", r"\bperl\s+-[a-zA-Z]*i", r"\brm\b", r"\bmv\b", r"\bcp\b",
    r"\bmkdir\b", r"\btouch\b", r"\bchmod\b", r"\bchown\b", r"\bln\b", r"\btruncate\b", r"\bpatch\b",
    r"\bgit\s+(add|commit|checkout|switch|restore|stash|merge|rebase|reset|apply|rm|mv|clean)\b",
    r"\bpython3?\s+-c\b.*open\(.*['\"]w", r"\bcat\s*<<", r"\binstall\b", r"\bunzip\b", r"\btar\s+-?x",
]


# --------------------------------------------------------------------------- #
# Path normalisation
# --------------------------------------------------------------------------- #

def normalize_path(p: str, cwd: str | None = None) -> str:
    """Return the path relative to the workspace root when possible, with a trailing
    '/' for directories that already exist. Absolute paths outside the root are
    returned as-is (absolute)."""
    if not p:
        return p
    expanded = os.path.expanduser(p)
    base = Path(cwd) if cwd else rndlib.ROOT
    ap = Path(expanded) if os.path.isabs(expanded) else (base / expanded)
    try:
        ap = ap.resolve(strict=False)
    except (OSError, RuntimeError):
        pass
    try:
        r = ap.relative_to(rndlib.ROOT)
        s = str(r)
        return s + ("/" if ap.is_dir() and s and not s.endswith("/") else "")
    except ValueError:
        return str(ap)


def _under_tmpdir(abs_path: str) -> bool:
    for var in ("TMPDIR", "CLAUDE_SCRATCHPAD_DIR", "RND_TMPDIR"):
        d = os.environ.get(var)
        if d and abs_path.startswith(os.path.realpath(d).rstrip("/") + "/"):
            return True
    return False


def _match_prefix_or_glob(rel_path: str, pattern: str) -> bool:
    if "*" in pattern or "?" in pattern:
        # directory globs: '.rnd/cases/RND-*/artifacts/' matches anything below
        if pattern.endswith("/"):
            return fnmatch.fnmatchcase(rel_path, pattern + "*") or fnmatch.fnmatchcase(rel_path.rstrip("/") + "/", pattern)
        return fnmatch.fnmatchcase(rel_path, pattern)
    if pattern.endswith("/"):
        return rel_path == pattern.rstrip("/") or rel_path.startswith(pattern)
    return rel_path == pattern


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #

def check_path_write(path: str, agent: str | None, policy: dict | None = None, cwd: str | None = None) -> tuple[bool, str]:
    """Is `agent` allowed to write `path`? Returns (allowed, reason)."""
    policy = policy or rndlib.load_policy()
    agent = (agent or "").lower()
    rel_path = normalize_path(path, cwd)

    # System paths: nobody writes there from this workspace.
    for blocked in policy["safety"]["blockedPathWrites"]:
        b = os.path.expanduser(blocked)
        if os.path.isabs(rel_path) and rel_path.startswith(b.rstrip("/")):
            return False, f"write to system path is blocked by policy: {blocked}"

    if agent in READONLY_AGENTS or agent in VALIDATOR_AGENTS:
        return False, f"agent '{agent}' is read-only and must not write files (return your report as your final message)"

    if agent in BUILDER_AGENTS:
        if os.path.isabs(rel_path):
            if rel_path.startswith(TEMP_PREFIXES) or _under_tmpdir(rel_path):
                return True, "temporary directory"
            return False, "builder may only write inside the workspace, its worktree, or a temporary directory (/tmp, $TMPDIR)"
        for allowed in policy["protectedPaths"]["builderAllowedWithinDenied"]:
            if _match_prefix_or_glob(rel_path, allowed):
                return True, f"allowed: {allowed}"
        for denied in policy["protectedPaths"]["builderDenied"]:
            if _match_prefix_or_glob(rel_path, denied):
                return False, (f"builder must not modify R&D infrastructure path '{denied}' "
                               f"(write PoC code under .rnd/cases/<CASE>/artifacts/ instead; the Lead records results via .claude/scripts/rnd.py)")
    return True, "ok"


def check_command(command: str, agent: str | None = None, policy: dict | None = None, cwd: str | None = None) -> tuple[bool, str]:
    """Global safety gate for shell commands (all agents, including the Lead)."""
    policy = policy or rndlib.load_policy()
    cmd = command.strip()
    scan = strip_heredocs(cmd)  # heredoc *data* (file contents) is not a command
    for pat in policy["safety"]["blockedCommandPatterns"]:
        if re.search(pat, scan):
            return False, f"command matches blocked pattern: /{pat}/"

    agent = (agent or "").lower()
    if agent in BUILDER_AGENTS:
        # Only the paths the command would actually write are checked; reading
        # /bin/sh or grepping .claude/scripts/ is fine.
        for token in write_targets(cmd, cwd):
            ok, why = check_path_write(token, agent, policy, cwd)
            if not ok:
                return False, f"builder shell write to protected path '{token}': {why}"
    return True, "ok"


def _path_tokens(cmd: str) -> list[str]:
    toks = []
    for t in re.split(r"[\s;|&()<>'\"`]+", cmd):
        t = t.strip()
        if not t or t.startswith("-"):
            continue
        if "/" in t or t in {".claude", ".codex", "scripts", "schemas", "rnd", "knowledge", "CLAUDE.md", "SPEC.md", ".gitignore"}:
            toks.append(t.rstrip("/") + ("/" if t.endswith("/") else ""))
    return toks


_QUOTED_RE = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")


def _strip_quoted(cmd: str) -> str:
    """Replace quoted arguments with '' so that words inside them (e.g. a --focus text
    containing '->' or 'captured') are treated as data, not as shell operators/commands.
    Command substitutions inside double quotes still run, so they are kept for scanning."""
    def repl(m: re.Match) -> str:
        tok = m.group(0)
        if tok.startswith("'"):
            return "''"                      # single quotes never expand
        inner = _substitutions(tok[1:-1])
        return f"'' ; {inner}" if inner else "''"
    return _QUOTED_RE.sub(repl, cmd)


# Inline `python3 -c` for read/test-only agents: reading is fine, writing / executing is not.
# Module aliasing (`import os as o`) is covered by matching the modules and the method names
# separately rather than only `os.unlink`.
_INLINE_PY_DENY_RE = re.compile(
    r"""open\s*\([^)]*(?:,\s*|mode\s*=\s*)["'][wax+]"""            # open(p, "w")
    r"""|\b(?:import|from)\s+(?:shutil|subprocess|pty|socket|ctypes|multiprocessing)\b"""
    r"""|\bos\s*\.\s*(?:remove|unlink|rmdir|removedirs|rename|replace|mkdir|makedirs|chmod|chown"""
    r"""|system|popen|exec[lv]p?e?|spawn\w*|kill|killpg|truncate|symlink|link)\b"""
    r"""|\b(?:shutil|subprocess)\s*\.|\bPopen\b|\b__import__\b|\bexec\s*\(|\beval\s*\("""
    r"""|\.\s*(?:write_text|write_bytes|writelines|unlink|rmdir|makedirs|mkdir|touch|rmtree|chmod|chown|rename)\s*\("""
)


def _token_present(token: str, unquoted: str) -> bool:
    t = token.strip()
    if not re.search(r"[A-Za-z]", t):
        return token in unquoted  # pure operators such as '>' or '>>' - substring on the unquoted text
    if t.startswith("|"):
        return re.search(r"\|\s*" + re.escape(t[1:].strip()) + r"(\s|$)", unquoted) is not None
    if t.startswith("-"):
        # option-style tokens: --output=file and -delete both count
        return re.search(r"(^|\s)" + re.escape(t) + r"(\s|=|$)", unquoted) is not None
    # word-like tokens (git add, apt, install ...) must start a word / command
    return re.search(r"(^|[\s;&|(])" + re.escape(t) + r"(\s|$)", unquoted) is not None


def check_reviewer_command(command: str, agent: str, policy: dict | None = None) -> tuple[bool, str]:
    """Allow-list shell gate for read-only reviewer / test-only validator agents."""
    policy = policy or rndlib.load_policy()
    cfg = policy["reviewerShell"]
    cmd = command.strip()
    if not cmd:
        return True, "empty"
    ok_global, why = check_command(cmd, agent, policy)
    if not ok_global:
        return False, why
    # absolute workspace paths are equivalent to relative ones for the allow-list
    unq = _strip_quoted(cmd).replace(str(rndlib.ROOT) + "/", "").replace("$CLAUDE_PROJECT_DIR/", "").replace("${CLAUDE_PROJECT_DIR}/", "")
    for tok in cfg["deniedTokens"]:
        if _token_present(tok, unq):
            # a redirect is tolerated only when its sole target is /dev/null
            if tok in {">", ">>"} and re.search(r">\s*/dev/null", unq) and not re.search(r">\s*(?!/dev/null)\S", unq.replace("2>&1", "")):
                continue
            return False, f"'{tok.strip()}' is not permitted for agent '{agent}' (read-only / test-only)"
    prefixes = list(cfg["allowedPrefixes"])
    if agent in VALIDATOR_AGENTS:
        prefixes += cfg["validatorExtraPrefixes"]
        # inline python is allowed for checks (ast.parse, json inspection) but not for writes
        for m in re.finditer(r"python3?\s+-c\s+(['\"])(.*?)\1", cmd, re.S):
            code = m.group(2)
            if _INLINE_PY_DENY_RE.search(code):
                return False, (f"inline python for agent '{agent}' must not write files, delete paths "
                               f"or spawn processes (reading, ast.parse and json inspection are fine)")
    # every segment of a pipeline / && chain must be allowed (quoted text already neutralised)
    segments = [s.strip() for s in _SEGMENT_SPLIT_RE.split(unq) if s.strip()]
    for seg in segments:
        seg_n = re.sub(r"^\s*(timeout\s+(--[a-z-]+=\S+\s+)?\d+[smh]?\s+)", "", seg)
        seg_n = re.sub(r"^\s*(cd\s+\S+\s*)$", "pwd", seg_n)
        if not any(seg_n.startswith(p.rstrip()) or seg_n.startswith(p) for p in prefixes):
            return False, f"command segment not on the read-only allow-list for '{agent}': {seg_n[:80]!r}"
    return True, "ok"


def scan_secrets(text: str, policy: dict | None = None) -> list[str]:
    policy = policy or rndlib.load_policy()
    hits = []
    for pat in policy["safety"]["secretPatterns"]:
        for m in re.finditer(pat, text):
            hits.append(f"{pat} -> {m.group(0)[:6]}…")
    return hits


def scan_diff(ref: str | None, policy: dict | None = None) -> list[str]:
    policy = policy or rndlib.load_policy()
    args = ["diff", "--no-color", "--unified=0"]
    if ref:
        args.append(ref)
    r = rndlib.git(*args)
    if r.returncode != 0:
        return [f"git diff failed: {r.stderr.strip()}"]
    problems = []
    added = "\n".join(l[1:] for l in r.stdout.splitlines() if l.startswith("+") and not l.startswith("+++"))
    for hit in scan_secrets(added, policy):
        problems.append(f"secret-like token in added lines: {hit}")
    names = rndlib.git("diff", "--name-only", *( [ref] if ref else [] )).stdout.split()
    for n in names:
        ok, why = check_path_write(n, "builder", policy)
        if not ok:
            problems.append(f"protected path changed: {n} ({why})")
    return problems


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("command"); c.add_argument("command"); c.add_argument("--agent", default=None)
    p = sub.add_parser("path"); p.add_argument("path"); p.add_argument("--agent", required=True)
    s = sub.add_parser("secrets"); s.add_argument("targets", nargs="+")
    d = sub.add_parser("diff"); d.add_argument("ref", nargs="?")
    a = ap.parse_args(argv)
    policy = rndlib.load_policy()
    if a.cmd == "command":
        agent = (a.agent or "").lower()
        if agent in REVIEWER_AGENTS or agent in VALIDATOR_AGENTS:
            ok, why = check_reviewer_command(a.command, agent, policy)
        else:
            ok, why = check_command(a.command, a.agent, policy)
        print(("ALLOW" if ok else "DENY") + f": {why}")
        return 0 if ok else 2
    if a.cmd == "path":
        ok, why = check_path_write(a.path, a.agent, policy)
        print(("ALLOW" if ok else "DENY") + f": {why}")
        return 0 if ok else 2
    if a.cmd == "secrets":
        total = 0
        for t in a.targets:
            for f in ([Path(t)] if Path(t).is_file() else [q for q in Path(t).rglob("*") if q.is_file()]):
                try:
                    hits = scan_secrets(f.read_text(encoding="utf-8", errors="ignore"), policy)
                except OSError:
                    continue
                for h in hits:
                    print(f"{f}: {h}")
                total += len(hits)
        print(f"{total} secret-like token(s)")
        return 2 if total else 0
    if a.cmd == "diff":
        probs = scan_diff(a.ref, policy)
        for pr in probs:
            print(pr)
        print("clean" if not probs else f"{len(probs)} problem(s)")
        return 2 if probs else 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
