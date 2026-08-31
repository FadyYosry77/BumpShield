#!/usr/bin/env python3
"""Build a deterministic, sanitized hackathon submission ZIP."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import stat
import zipfile


TOP_LEVEL_FILES = {
    ".gitignore",
    "BumpShield_PROJECT_GOAL.md",
    "README.md",
    "SUBMISSION.md",
    "pyproject.toml",
}
TOP_LEVEL_DIRECTORIES = {
    "benchmark",
    "bumpshield",
    "demo_ui",
    "docs",
    "integration-fixtures",
    "scripts",
    "showcase",
    "submission",
    "tests",
}
EXCLUDED_PARTS = {
    ".git",
    ".m2",
    ".maven-cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "final-runtime",
    "runtime",
    "state",
    "target",
    "venv",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_NAMES = {".env", ".env.local", "credentials.json"}
PRIVATE_MARKERS = (
    b"/home/" + b"hp/",
    b"BEGIN OPENSSH PRIVATE KEY",
    b"BEGIN RSA PRIVATE KEY",
    b"BEGIN EC PRIVATE KEY",
)
TEXT_SUFFIXES = {
    ".css",
    ".csv",
    ".html",
    ".java",
    ".json",
    ".md",
    ".properties",
    ".py",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def included_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if relative.parts[0] not in TOP_LEVEL_DIRECTORIES:
            continue
        if any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in relative.parts):
            continue
        if path.name in EXCLUDED_NAMES or path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    for name in TOP_LEVEL_FILES:
        path = root / name
        if not path.is_file():
            raise SystemExit(f"Required submission file is missing: {name}")
        files.append(path)
    return sorted(set(files), key=lambda item: item.relative_to(root).as_posix())


def validate_text_files(root: Path, files: list[Path]) -> None:
    problems: list[str] = []
    for path in files:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.relative_to(root).as_posix() == "scripts/build_submission_archive.py":
            # This file necessarily contains the literal key headers it scans.
            continue
        data = path.read_bytes()
        # The replay tests deliberately assert that this private path marker is
        # absent from bundles; the negative assertion is not leaked path data.
        negative_assertion = b'assert "' + PRIVATE_MARKERS[0] + b'" not in text'
        data = data.replace(negative_assertion, b"")
        if any(marker in data for marker in PRIVATE_MARKERS):
            problems.append(path.relative_to(root).as_posix())
    if problems:
        joined = ", ".join(problems)
        raise SystemExit(f"Private path or key marker found in submission files: {joined}")


def write_archive(root: Path, output: Path, files: list[Path]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = PurePosixPath("BumpShield")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = PurePosixPath(path.relative_to(root).as_posix())
            info = zipfile.ZipInfo(str(prefix / relative), date_time=(2026, 8, 31, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "BumpShield-hackathon-submission.zip",
        help="ZIP destination (default: next to the repository)",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.expanduser().resolve()
    if root == output or root in output.parents:
        raise SystemExit("Output must be outside the source repository")
    files = included_files(root)
    validate_text_files(root, files)
    write_archive(root, output, files)
    print(f"Archive: {output}")
    print(f"Files: {len(files)}")
    print(f"Bytes: {output.stat().st_size}")
    print(f"SHA-256: {sha256(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
