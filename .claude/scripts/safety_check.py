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
import shlex
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

# Interpreters: a heredoc fed to one of these is executed, not stored.
_INTERPRETER_RE = re.compile(r"(^|[\s;&|(])(ba|z|da)?sh\b|\bpython3?\b|\bperl\b|\bnode\b|\bruby\b|\beval\b|\bsource\b|\bxargs\b")
_HEREDOC_RE = re.compile(r"(?P<line>[^\n]*<<-?\s*(?P<q>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=q)[^\n]*)\n(?P<body>.*?)\n[ \t]*(?P=tag)[ \t]*(?=\n|$)", re.S)

# Commands whose (non-option) arguments are written to or deleted.
_WRITE_CMDS = {"rm", "mv", "cp", "mkdir", "touch", "chmod", "chown", "ln", "truncate", "patch",
               "tee", "install", "unzip", "rmdir", "shred", "dd", "cpio"}
_GIT_WRITE_SUBCMDS = {"add", "commit", "checkout", "switch", "restore", "stash", "merge", "rebase",
                      "reset", "apply", "rm", "mv", "clean", "worktree"}
_REDIRECT_TOKEN_RE = re.compile(r"^\d*(>>?\|?|&>>?)$")
_SUBST_RE = re.compile(r"\$\((?P<paren>[^()]*(?:\([^()]*\)[^()]*)*)\)|`(?P<tick>[^`]*)`", re.S)

# Writes performed by an interpreter one-liner or heredoc body.
_INTERP_WRITE_RE = re.compile(
    r"""(?:\bio\.)?\bopen\s*\(\s*["'](?P<open>[^"']+)["']\s*,\s*(?:mode\s*=\s*)?["'][^"']*[wax+][^"']*["']"""
    r"""|\b(?:Path|PurePath)\s*\(\s*["'](?P<path>[^"']+)["']\s*\)\s*(?:\.\s*\w+\s*\([^)]*\)\s*)*"""
    r"""\.\s*(?:write_text|write_bytes|writelines|unlink|mkdir|touch|rename|replace|chmod|rmdir|symlink_to|hardlink_to)\s*\("""
    r"""|\bos\s*\.\s*(?:remove|unlink|rmdir|removedirs|rename|replace|mkdir|makedirs|chmod|chown|truncate)\s*\(\s*["'](?P<os>[^"']+)["']"""
    r"""|\bshutil\s*\.\s*(?:rmtree|move|copy|copy2|copyfile|copytree)\s*\(\s*["'](?P<sh>[^"']+)["']"""
    r"""|\b(?:writeFileSync|appendFileSync|createWriteStream|unlinkSync|rmSync|rmdirSync|mkdirSync|renameSync|copyFileSync|truncateSync)"""
    r"""\s*\(\s*["'](?P<node>[^"']+)["']""",
)


def _substitutions(text: str) -> str:
    """Command substitutions in `text` - they execute even inside double quotes. A substitution
    escaped by an odd number of backslashes is inert, matching the shell."""
    out = []
    for m in _SUBST_RE.finditer(text):
        before = text[:m.start()]
        if (len(before) - len(before.rstrip("\\"))) % 2:
            continue
        out.append(m.group("paren") or m.group("tick") or "")
    return " ; ".join(out)


def split_heredocs(cmd: str) -> tuple[str, list[str]]:
    """Return (command text without heredoc bodies, bodies that will actually execute).

    A body is inert data unless its delimiter is unquoted (the shell expands it) or the line
    feeds an interpreter (`bash <<EOF`, `cat <<EOF | node`)."""
    live: list[str] = []

    def repl(m: re.Match) -> str:
        line, tag, body = m.group("line"), m.group("tag"), m.group("body")
        before, after = line.split("<<", 1)[0], line.split("<<", 1)[1]
        if _INTERPRETER_RE.search(before) or _INTERPRETER_RE.search(after):
            live.append(body)                       # executed by an interpreter
        elif not m.group("q"):
            live.append(_substitutions(body))       # unquoted delimiter: substitutions expand
        return line + "\n" + tag

    stripped = _HEREDOC_RE.sub(repl, cmd)
    return stripped, [b for b in live if b.strip()]


def normalise_text(text: str) -> str:
    """Join line continuations and drop comments, leaving quoting intact. Used for the
    destructive-command patterns, which must see real command text and not the inside of a
    quoted argument (`grep 'git reset --hard'` is a search, not a command)."""
    text = text.replace("\\\n", " ")
    out, quote, esc = [], "", False
    for ch in text:
        if esc:
            out.append(ch)
            esc = False
            continue
        if ch == "\\" and quote != "'":
            out.append(ch)
            esc = True
            continue
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (not out or out[-1] in " \t\n;&|("):
            while True:                     # skip to end of line
                nl = text.find("\n", len("".join(out)))
                break
            out.append("\n")
            quote = "#"                     # reuse the flag as "in comment"
            continue
        out.append(ch)
    joined = "".join(out)
    return re.sub(r"(?m)(^|(?<=[\s;&|(]))#[^\n]*", "", joined)


def tokenize(cmd: str) -> list[str]:
    """Shell words and operators, with quoting, escapes, comments and line continuations
    resolved by `shlex`. Falls back to whitespace splitting if the text does not parse
    (an unbalanced quote, say), because the caller must still get *some* view of it."""
    text = cmd.replace("\\\n", " ")
    lex = shlex.shlex(text, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:
        return [t for t in re.split(r"\s+", text) if t]


def blank_quoted(text: str) -> str:
    """Replace the *content* of quoted regions with nothing, keeping the shell structure.
    A destructive command written inside quotes is an argument, not a command."""
    out, quote, esc = [], "", False
    for ch in text:
        if esc:
            esc = False
            continue
        if ch == "\\" and quote != "'":
            esc = True
            continue
        if quote:
            if ch == quote:
                quote = ""
                out.append(quote or ch)
            continue
        if ch in "'\"":
            quote = ch
            out.append("''")
            continue
        out.append(ch)
    return "".join(out)


_OPERATORS = {";", "&&", "||", "|", "&", "\n"}


def statements(tokens: list[str]) -> list[str]:
    """Token stream split into statements, each joined back into text. Used to test the
    destructive-command patterns in command position only."""
    out, cur = [], []
    for t in tokens:
        if t in _OPERATORS:
            if cur:
                out.append(" ".join(cur))
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(" ".join(cur))
    return out


def _interp_targets(text: str) -> list[str]:
    out = []
    for m in _INTERP_WRITE_RE.finditer(text):
        out.extend(g for g in (m.group("open"), m.group("path"), m.group("os"), m.group("sh"), m.group("node")) if g)
    return out


def _token_write_targets(tokens: list[str]) -> list[str]:
    """Paths the tokenised command would create, modify or delete."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _REDIRECT_TOKEN_RE.match(tok):
            if i + 1 < len(tokens):
                out.append(tokens[i + 1])
            i += 2
            continue
        cmd_word = tok.rsplit("/", 1)[-1]
        if cmd_word in _WRITE_CMDS:
            j = i + 1
            while j < len(tokens) and tokens[j] not in {";", "&&", "||", "|", "&", "\n"} and not _REDIRECT_TOKEN_RE.match(tokens[j]):
                if not tokens[j].startswith("-"):
                    out.append(tokens[j])
                j += 1
            i = j
            continue
        if cmd_word in {"sed", "perl"}:
            j, in_place, args = i + 1, False, []
            while j < len(tokens) and tokens[j] not in {";", "&&", "||", "|", "&"}:
                if tokens[j].startswith("-") and "i" in tokens[j][1:]:
                    in_place = True
                elif not tokens[j].startswith("-"):
                    args.append(tokens[j])
                j += 1
            if in_place:
                out.extend(args[1:])                # first non-option word is the expression
            i = j
            continue
        if cmd_word == "git":
            j = i + 1
            while j < len(tokens) and (tokens[j].startswith("-") or (j > i + 1 and tokens[j - 1] in {"-C", "-c", "--git-dir", "--work-tree"})):
                j += 1
            if j < len(tokens) and tokens[j] in _GIT_WRITE_SUBCMDS:
                out.append(".git/")
            i = j + 1
            continue
        if cmd_word in {"python", "python3", "node", "perl", "ruby"}:
            for j in range(i + 1, len(tokens)):
                if tokens[j] in {"-c", "-e"} and j + 1 < len(tokens):
                    out.extend(_interp_targets(tokens[j + 1]))
                if tokens[j] in {";", "&&", "||", "|", "&"}:
                    break
        i += 1
    return out


def write_targets(cmd: str, cwd: str | None = None) -> list[str]:
    """Paths a shell command would create, modify or delete.

    Relative paths are resolved against the workspace (or `cwd`), **not** against any `cd`
    inside the command: modelling shell control flow with text matching does not work, and
    guessing produced both bypasses and false positives. Use absolute paths for scratch work
    outside the workspace. This is a best-effort signal, not a write boundary - the enforced
    boundary is the tool-level guard on Write/Edit and the Claude Code permission settings.
    """
    stripped, live_bodies = split_heredocs(cmd)
    tokens = tokenize(stripped)
    targets = _token_write_targets(tokens)
    for body in live_bodies:                        # heredoc bodies keep their own quoting
        targets += _interp_targets(body)
        targets += _token_write_targets(tokenize(body))
    subs = _substitutions(stripped)
    if subs:
        targets += _token_write_targets(tokenize(subs))
        targets += _interp_targets(subs)
    # a `cd` into a protected directory makes every relative write in the same command suspect
    protected_cd = []
    for i, t in enumerate(tokens):
        if t not in ("cd", "pushd"):
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].startswith("-") and tokens[j] != "--":
            j += 1
        if j < len(tokens) and tokens[j] == "--":
            j += 1
        if j < len(tokens) and tokens[j] not in {";", "&&", "||", "|", "&"} and not tokens[j].startswith("-"):
            protected_cd.append(tokens[j])
    cleaned: list[str] = []
    for t in targets:
        if not t or t in {"/dev/null", "/dev/stdout", "/dev/stderr", "&1", "&2"} or t.startswith("-"):
            continue
        cleaned.append(t)
        if not os.path.isabs(t):
            for d in protected_cd:
                if not os.path.isabs(d):
                    cleaned.append(os.path.normpath(os.path.join(d, t)))
    return cleaned


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
    """Match a path against a policy pattern component by component, so a `*` never crosses a
    path separator. Without this, the artifacts exception `.rnd/cases/RND-*/artifacts/` would
    also admit `.rnd/cases/<CASE>/research/artifacts/`, which is protected."""
    pat_parts = [x for x in pattern.strip("/").split("/") if x]
    path_parts = [x for x in rel_path.strip("/").split("/") if x]
    if not pat_parts or not path_parts:
        return False
    if pattern.endswith("/"):                        # directory prefix: match the leading parts
        if len(path_parts) < len(pat_parts):
            return False
        candidate = path_parts[:len(pat_parts)]
    else:                                            # exact path
        if len(path_parts) != len(pat_parts):
            return False
        candidate = path_parts
    return all(fnmatch.fnmatchcase(c, q) for c, q in zip(candidate, pat_parts))


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
    stripped, live_bodies = split_heredocs(cmd)
    # Two views: the raw text (keeps quoting, so patterns written against quoted arguments
    # still match) and the token stream (resolves continuations, comments and quoting).
    subs = _substitutions(stripped)
    inner = live_bodies + ([subs] if subs else [])      # interpreter bodies and substitutions
    texts = [stripped] + inner
    # In shell text, quoted argument content is blanked so a search string such as
    # `grep "git reset --hard"` is not mistaken for the command itself. Inside an interpreter
    # body a string literal can still be executed (`os.system("...")`), so those are scanned raw.
    searchable = [blank_quoted(normalise_text(stripped))]
    searchable += inner + [blank_quoted(normalise_text(t)) for t in inner]
    # Token statements resolve quoting and line continuations, and are matched in command
    # position only, so `rm -rf "/"` and a continued `git \<newline> reset --hard` are caught.
    anchored = [st for t in texts for st in statements(tokenize(normalise_text(t)))]
    for pat in policy["safety"]["blockedCommandPatterns"]:
        for view in searchable:
            if re.search(pat, view):
                return False, f"command matches blocked pattern: /{pat}/"
        for st in anchored:
            if re.match(pat, st):
                return False, f"command matches blocked pattern: /{pat}/"

    agent = (agent or "").lower()
    if agent in BUILDER_AGENTS:
        git_ok = agent in policy["protectedPaths"].get("gitWriteAgents", [])
        for token in write_targets(cmd, cwd):
            if token == ".git/" and git_ok:
                continue                             # commits in its own worktree are its job
            ok, why = check_path_write(token, agent, policy, cwd)
            if not ok:
                return False, (f"builder shell write to protected path '{token}': {why}. "
                               f"Relative paths are read as workspace paths; use an absolute path "
                               f"for scratch files outside it.")
    return True, "ok"


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
_PY_WRITE_VERBS = (r"remove|unlink|rmdir|removedirs|rename|replace|mkdir|makedirs|chmod|chown"
                   r"|system|popen|exec[lv]p?e?|spawn\w*|kill|killpg|truncate|symlink|link|rmtree"
                   r"|move|copy|copy2|copyfile|copytree|run|call|check_call|check_output|Popen"
                   r"|write_text|write_bytes|writelines|touch")
_PY_DANGEROUS_MODULES = ("os", "shutil", "subprocess", "pty", "socket", "ctypes", "multiprocessing")
_PY_ALWAYS_DENY_RE = re.compile(
    r"""open\s*\([^)]*(?:,\s*|mode\s*=\s*)["'][^"']*[wax+]"""     # open(p, "w" / "a" / "r+")
    r"""|\bPopen\b|\b__import__\b|\bexec\s*\(|\beval\s*\("""
    r"""|\.\s*(?:write_text|write_bytes|writelines|unlink|rmdir|makedirs|mkdir|touch|rmtree|chmod|chown)\s*\("""
)
_PY_PATH_RECEIVER_RE = re.compile(r"\b(\w+)\s*=\s*(?:Path|PurePath)\s*\(")
_PY_PATH_CALL_RE = re.compile(r"\.\s*(?:replace|rename)\s*\(")


def _inline_python_writes(code: str) -> bool:
    """True when a `python3 -c` one-liner writes, deletes or spawns. Import aliases and
    variables holding a Path are resolved, so `import os as o; o.remove(p)` and
    `p = Path(x); p.rename(y)` are caught while `os.getcwd()`, `open(p).read()` and
    `"a".replace("b")` stay allowed."""
    if _PY_ALWAYS_DENY_RE.search(code):
        return True
    names = set(_PY_DANGEROUS_MODULES)
    for m in re.finditer(r"\bimport\s+([\w., ]+)", code):
        for part in m.group(1).split(","):
            words = part.split()
            if words and words[0] in _PY_DANGEROUS_MODULES:
                names.add(words[-1])               # `import os as o` -> o ; `import os` -> os
    if re.search(r"\b(?:" + "|".join(re.escape(n) for n in sorted(names)) + r")\s*\.\s*(?:" + _PY_WRITE_VERBS + r")\s*\(", code):
        return True
    # `from os import remove` / `from shutil import rmtree as nuke`: only write verbs matter,
    # so `from os import getcwd` stays allowed
    for m in re.finditer(r"\bfrom\s+(?:" + "|".join(_PY_DANGEROUS_MODULES) + r")\s+import\s+([^\n;]+)", code):
        for part in m.group(1).split(","):
            words = part.replace("(", "").replace(")", "").split()
            if not words:
                continue
            imported, local = words[0], words[-1]
            if re.fullmatch(_PY_WRITE_VERBS, imported) and re.search(r"\b" + re.escape(local) + r"\s*\(", code):
                return True
    # a variable holding a Path, used for a rename/replace
    for m in _PY_PATH_RECEIVER_RE.finditer(code):
        if re.search(r"\b" + re.escape(m.group(1)) + r"\s*" + _PY_PATH_CALL_RE.pattern, code):
            return True
    if re.search(r"\b(?:Path|PurePath)\s*\([^)]*\)\s*(?:\.\s*\w+\s*\([^)]*\)\s*)*" + _PY_PATH_CALL_RE.pattern, code):
        return True
    return False


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
            if _inline_python_writes(code):
                return False, (f"inline python for agent '{agent}' must not write files, delete paths "
                               f"or spawn processes (reading, ast.parse and json inspection are fine)")
    # every segment of a pipeline / && chain must be allowed (quoted text already neutralised)
    segments = [s.strip() for s in re.split(r"&&|\|\||;|\n|\||(?<![>&])&(?!&)", unq) if s.strip()]
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
