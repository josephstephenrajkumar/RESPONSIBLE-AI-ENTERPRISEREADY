#!/usr/bin/env python3
"""Claude Code PreToolUse hook: enforce "no secret is documented or uploaded to git".

Wired from .claude/settings.json. Reads the tool call as JSON on stdin and:
  * Bash  `git commit ...`  -> scans staged + unstaged + untracked files   (scripts/check_no_secrets.py --pending)
  * Bash  `git push ...`    -> scans every tracked file                    (scripts/check_no_secrets.py --all)
  * Write / Edit / NotebookEdit -> scans the text about to be written, unless the target is
    outside the repository or ignored by .gitignore (for example backend/.env).

Exit 0 lets the tool run. Exit 2 blocks it and feeds the findings back to Claude.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SCANNER = os.path.join(ROOT, "scripts", "check_no_secrets.py")

GIT_OPTS = r"(?:\s+(?:-C\s+\S+|-c\s+\S+|--no-pager|--git-dir=\S+|--work-tree=\S+))*"
COMMIT_RE = re.compile(r"\bgit" + GIT_OPTS + r"\s+commit\b")
PUSH_RE = re.compile(r"\bgit" + GIT_OPTS + r"\s+push\b")


def run_scanner(args, stdin_text=None) -> int:
    r = subprocess.run(
        [sys.executable, SCANNER, *args],
        cwd=ROOT,
        input=stdin_text,
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        return 0
    sys.stderr.write("BLOCKED by the no-secrets rule (CLAUDE.md, docs/NO_SECRETS_IN_GIT.md).\n")
    sys.stderr.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 1:
        sys.stderr.write("The scanner itself failed, so the action is blocked until it can run.\n")
    return 2


def is_exempt_path(path: str) -> bool:
    """True for paths that can never reach git: outside the repo, or ignored by .gitignore."""
    if not path:
        return False
    full = os.path.abspath(path if os.path.isabs(path) else os.path.join(ROOT, path))
    if os.path.commonpath([full, ROOT]) != ROOT:
        return True
    r = subprocess.run(["git", "check-ignore", "-q", full], cwd=ROOT, capture_output=True)
    return r.returncode == 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool == "Bash":
        cmd = tool_input.get("command") or ""
        if COMMIT_RE.search(cmd):
            return run_scanner(["--pending", "--quiet"])
        if PUSH_RE.search(cmd):
            return run_scanner(["--all", "--quiet"])
        return 0

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if is_exempt_path(target):
            return 0
        texts = [tool_input[k] for k in ("content", "new_string", "new_source") if isinstance(tool_input.get(k), str)]
        for edit in tool_input.get("edits") or []:
            if isinstance(edit, dict) and isinstance(edit.get("new_string"), str):
                texts.append(edit["new_string"])
        if not texts:
            return 0
        label = os.path.relpath(os.path.abspath(target), ROOT) if target else "<edit>"
        return run_scanner(["--text", "--label", label, "--quiet"], stdin_text="\n".join(texts))

    return 0


if __name__ == "__main__":
    sys.exit(main())
