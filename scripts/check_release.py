"""Fail closed on common private/large artifacts in the Git index.

This is a supplementary release check, not a de-identification tool or secret
scanner guarantee. Review full Git history and remote artifacts separately.
The content inspected is the staged Git blob, not only the working copy.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath, Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SUFFIXES = {".py", ".md", ".toml", ".lock", ".yml", ".yaml", ".txt"}
ALLOWED_DOTFILES = {".gitignore", ".python-version"}
FORBIDDEN_PARTS = {"WSI", "data", "outputs", "models", ".venv", "local", ".cache", "__pycache__"}
PATTERNS = {
    "local absolute path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "GitHub credential": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "possible clinical accession": re.compile(r"\bH\d{2}[-−]\d{3,}"),
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], stderr=subprocess.DEVNULL)


def main() -> int:
    try:
        names = [name.decode("utf-8") for name in git("ls-files", "-z").split(b"\0") if name]
    except subprocess.CalledProcessError:
        print("Not a Git repository. Initialize Git and explicitly stage the intended release files first.")
        return 1
    if not names:
        print("No tracked/staged release files found. Stage the intended files before checking.")
        return 1
    problems: list[str] = []
    for name in names:
        path = PurePosixPath(name)
        if set(path.parts) & FORBIDDEN_PARTS:
            problems.append(f"{name}: forbidden input/output/cache directory")
        if path.name not in ALLOWED_DOTFILES and path.suffix.lower() not in ALLOWED_SUFFIXES:
            problems.append(f"{name}: not an allowlisted source/documentation file")
        content = git("show", f":{name}")
        if len(content) > 3_000_000:
            problems.append(f"{name}: unusually large release file")
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{name}: non-text content")
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(decoded):
                # Report categories and filenames, never the matched secret.
                problems.append(f"{name}: {label}")
    if problems:
        print("Release check FAILED:")
        print("\n".join(problems))
        return 1
    print(f"Release check passed for {len(names)} staged files. Review history and content manually as well.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
