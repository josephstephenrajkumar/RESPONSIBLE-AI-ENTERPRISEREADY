#!/usr/bin/env python3
"""Secret scanner for Responsible AI EnterpriseReady.

Rule: no secret value is ever documented in this repository or uploaded to git.
This script enforces it. Standard library only, so it runs anywhere python3 does.

Modes (exactly one):
  --staged          the index only: what `git commit` would record        (git pre-commit hook)
  --pending         index + unstaged changes + untracked files            (Claude hook before `git commit`)
  --all             every tracked file                                    (git pre-push hook, Claude hook before `git push`, CI)
  --files PATH...   the named files
  --text            text on stdin; --label NAME names it in the report    (Claude hook before Write/Edit)

Exit codes: 0 clean, 1 findings, 2 could not scan.

A line that shows a documented placeholder and never a real value can be excused by
putting `secret-scan:allow <reason>` on that same line.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys

ALLOW_MARKER = "secret-scan:allow"
MAX_FILE_BYTES = 5 * 1024 * 1024

SKIP_PATH_RE = re.compile(
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Pipfile\.lock|uv\.lock)$"
    r"|\.(lock|min\.js|map|svg|png|jpe?g|gif|ico|webp|pdf|docx|xlsx|pptx|zip|gz|tgz|woff2?|ttf|eot)$",
    re.I,
)

# Files that must never be committed regardless of content. `.env.example` style templates are allowed.
FORBIDDEN_NAME_RE = re.compile(
    r"(^|/)("
    r"\.env|\.env\.(?!example$|template$|sample$)[^/]+"
    r"|[^/]*\.(pem|p12|pfx|jks|keystore)"
    r"|id_rsa[^/]*|id_ed25519[^/]*|id_ecdsa[^/]*"
    r"|[^/]*\.tfstate(\.backup)?"
    r"|credentials|credentials\.json|\.netrc|\.pypirc"
    r"|infra-inputs-dev\.md"
    r")$",
    re.I,
)

# Values that are clearly placeholders, checked against the captured value of a match.
PLACEHOLDER_RE = re.compile(
    r"""^(?:
        <[^>]*>                                  # <your-key>
      | \$\{[^}]*\}                              # ${VAR} or ${VAR:-default}
      | \$[A-Za-z_][A-Za-z0-9_]*                 # $VAR
      | \{\{[^}]*\}\}                            # {{ templated }}
      | \*{3,} | x{3,} | X{3,} | \.{3,}
      | (?:your|my|insert|replace|enter|put)[-_ ].*
      | change[-_]?me.* | changeit | placeholder.* | example.* | sample.* | dummy.* | fake.* | mock.*
      | redacted.* | \[redacted\] | masked.*
      | sk-local-dev-.*                          # docker-compose LiteLLM keys, committed on purpose
      | password | passw0rd | secret | postgres | admin | root | test | testing | localdev | local
      | none | null | nil | undefined | unset | todo | tbd | n/a
    )$""",
    re.I | re.X,
)
PLACEHOLDER_SUBSTR = ("example", "placeholder", "redacted", "xxxx", "sk-local-dev-", "<", ">", "${", "}}")


def is_placeholder(value: str) -> bool:
    v = value.strip().strip("\"'`")
    if PLACEHOLDER_RE.match(v):
        return True
    low = v.lower()
    return any(s in low for s in PLACEHOLDER_SUBSTR)


def shannon(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def looks_random(value: str) -> bool:
    """Generated keys mix digits with both letter cases, or are long and high-entropy.
    Identifiers such as `settings.db_password` or `random_password.db.result` are neither."""
    v = value.strip().strip("\"'`")
    digits = sum(ch.isdigit() for ch in v)
    if digits >= 2 and any(ch.isupper() for ch in v) and any(ch.islower() for ch in v):
        return True
    return len(v) >= 32 and shannon(v) >= 4.0


# (rule name, regex whose group 1 is the value, apply looks_random heuristic)
RULES = [
    ("aws-access-key-id", re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b"), False),
    ("aws-secret-access-key", re.compile(r"(?i)aws_secret_access_key\b\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{40})"), False),
    ("private-key-block", re.compile(r"(-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----)"), False),
    ("groq-api-key", re.compile(r"\b(gsk_[A-Za-z0-9]{20,})\b"), False),
    ("anthropic-api-key", re.compile(r"\b(sk-ant-[A-Za-z0-9_-]{20,})\b"), False),
    ("openai-or-litellm-key", re.compile(r"(?<![A-Za-z0-9_-])(sk-(?!ant-)[A-Za-z0-9_-]{20,})\b"), False),
    ("github-token", re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"), False),
    ("slack-token", re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"), False),
    ("google-api-key", re.compile(r"\b(AIza[0-9A-Za-z_-]{35})\b"), False),
    ("jwt", re.compile(r"\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"), False),
    ("url-with-password", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@\"']+:([^\s/@\"']{6,})@"), True),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{20,})"), True),
    (
        "credential-assignment",
        re.compile(
            r"(?i)\b[A-Za-z0-9_-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key"
            r"|private[_-]?key|master[_-]?key|salt[_-]?key|signing[_-]?key|encryption[_-]?key)\b"
            r"\s*[:=]\s*[\"']?([A-Za-z0-9/+_.=-]{16,})"
        ),
        True,
    ),
]


def mask(value: str) -> str:
    if value.startswith("-----BEGIN"):
        return value
    return f"{value[:4]}…({len(value)} chars)"


def scan_lines(path: str, lines, start_line: int = 1):
    findings = []
    for lineno, line in enumerate(lines, start=start_line):
        if ALLOW_MARKER in line.lower():
            continue
        specific_hit = False
        for name, rx, needs_random in RULES:
            if needs_random and specific_hit:
                continue  # a format-specific rule already named this line; skip the generic heuristics
            for m in rx.finditer(line):
                value = m.group(1)
                if is_placeholder(value):
                    continue
                if needs_random and not looks_random(value):
                    continue
                findings.append((path, lineno, name, mask(value)))
                if not needs_random:
                    specific_hit = True
                break
    return findings


# ----------------------------------------------------------------- git helpers
def repo_root() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git(root: str, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def parse_added_lines(diff_text: str):
    """Yield (path, lineno, text) for every added line of a unified diff produced with -U0."""
    path = None
    lineno = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            p = raw[4:]
            path = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
        elif raw.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
            lineno = int(m.group(1)) if m else 0
        elif raw.startswith("+"):
            if path and not SKIP_PATH_RE.search(path):
                yield path, lineno, raw[1:]
            lineno += 1
        elif raw.startswith(("-", "\\", "diff ", "index ", "new file", "deleted file", "similarity", "rename", "Binary")):
            continue
        else:
            lineno += 1


def scan_diff(diff_text: str):
    findings = []
    by_path: dict[str, list[tuple[int, str]]] = {}
    for path, lineno, text in parse_added_lines(diff_text):
        by_path.setdefault(path, []).append((lineno, text))
    for path, items in by_path.items():
        for lineno, text in items:
            findings.extend(scan_lines(path, [text], start_line=lineno))
    return findings


def read_text_file(path: str) -> str | None:
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def scan_files(root: str | None, paths):
    findings = []
    for rel in paths:
        if SKIP_PATH_RE.search(rel):
            continue
        full = os.path.join(root, rel) if root and not os.path.isabs(rel) else rel
        text = read_text_file(full)
        if text is None:
            continue
        findings.extend(scan_lines(rel, text.splitlines()))
    return findings


# Vite env files under frontend/ hold public build-time values (they ship in the browser bundle), so the
# filename rule does not apply to them. Their content is still scanned like any other file.
FORBIDDEN_NAME_EXEMPT_RE = re.compile(r"(^|/)frontend/\.env(\.[^/]+)?$")


def _is_public_certificate_bundle(path: str) -> bool:
    """A .pem that holds only CERTIFICATE blocks (a CA bundle) is public material, not a secret."""
    root = repo_root()
    full = os.path.join(root, path) if root and not os.path.isabs(path) else path
    text = read_text_file(full)
    if text is None:
        return False
    return "BEGIN CERTIFICATE" in text and "PRIVATE KEY" not in text


def forbidden_names(paths):
    out = set()
    for p in paths:
        if not FORBIDDEN_NAME_RE.search(p) or FORBIDDEN_NAME_EXEMPT_RE.search(p):
            continue
        if p.lower().endswith(".pem") and _is_public_certificate_bundle(p):
            continue
        out.add(p)
    return sorted(out)


# ------------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--pending", action="store_true")
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--files", nargs="+", metavar="PATH")
    mode.add_argument("--text", action="store_true")
    ap.add_argument("--label", default="<text>", help="name shown for --text input")
    ap.add_argument("--quiet", action="store_true", help="print nothing when clean")
    args = ap.parse_args(argv)

    findings = []
    bad_names = []

    if args.text:
        findings = scan_lines(args.label, sys.stdin.read().splitlines())
    elif args.files:
        root = repo_root()
        findings = scan_files(root, args.files)
        bad_names = forbidden_names(args.files)
    else:
        root = repo_root()
        if not root:
            print("secret scan: not inside a git repository", file=sys.stderr)
            return 2
        try:
            if args.staged:
                findings = scan_diff(git(root, "diff", "--cached", "-U0", "--no-color", "--diff-filter=ACMR"))
                paths = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR").split()
                bad_names = forbidden_names(paths)
            elif args.pending:
                findings = scan_diff(git(root, "diff", "--cached", "-U0", "--no-color", "--diff-filter=ACMR"))
                findings += scan_diff(git(root, "diff", "-U0", "--no-color", "--diff-filter=ACMR"))
                untracked = [p for p in git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0") if p]
                findings += scan_files(root, untracked)
                paths = set(untracked)
                paths.update(git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR").split())
                paths.update(git(root, "diff", "--name-only", "--diff-filter=ACMR").split())
                bad_names = forbidden_names(paths)
            else:  # --all
                tracked = [p for p in git(root, "ls-files", "-z").split("\0") if p]
                findings = scan_files(root, tracked)
                bad_names = forbidden_names(tracked)
        except RuntimeError as exc:
            print(f"secret scan: {exc}", file=sys.stderr)
            return 2

    # de-duplicate (a line can be reached twice in --pending when staged and unstaged overlap)
    findings = sorted(set(findings))

    if not findings and not bad_names:
        if not args.quiet:
            print("secret scan: clean")
        return 0

    total = len(findings) + len(bad_names)
    print(f"secret scan: {total} finding(s). Nothing was written, committed or pushed.")
    for path, lineno, name, shown in findings:
        print(f"  {path}:{lineno}  {name}  {shown}")
    for p in bad_names:
        print(f"  {p}  forbidden-file (must never be committed)")
    print(
        "Fix: replace the value with a placeholder or with the name of where it lives (Secrets Manager / Parameter Store / env var).\n"
        "Real values belong only in AWS Secrets Manager or a gitignored local .env. Never bypass with --no-verify.\n"
        f"A documented placeholder that is not a real value can be excused by adding `{ALLOW_MARKER} <reason>` to that line."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
