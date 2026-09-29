from __future__ import annotations

from pathlib import Path

# Runtime/generated paths that package hygiene treats as transient artifacts.
TRANSIENT_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".runtime",
}
TRANSIENT_SUFFIXES = {".pyc", ".pyo", ".tmp", ".swp"}

# Dependency/VCS trees are not project-owned source and must never be scanned for
# repository network-bypass policy. They are also excluded from release manifests,
# but unlike TRANSIENT_PARTS they do not by themselves make a source checkout dirty.
NON_PROJECT_SOURCE_PARTS = {".venv", "venv", "node_modules", ".git"}
SOURCE_SCAN_EXCLUDED_PARTS = TRANSIENT_PARTS | NON_PROJECT_SOURCE_PARTS
RELEASE_EXCLUDED_NAMES = {"CONTROL_PLANE_MANIFEST.json", ".DS_Store", "Thumbs.db"}


def relative_path(path: Path, root: Path) -> Path:
    return path.relative_to(root)


def _has_part(path: Path, root: Path, excluded: set[str]) -> bool:
    rel = relative_path(path, root)
    return any(part in excluded for part in rel.parts)


def has_transient_part(path: Path, root: Path) -> bool:
    return _has_part(path, root, TRANSIENT_PARTS)


def has_transient_suffix(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in TRANSIENT_SUFFIXES


def is_project_source(path: Path, root: Path) -> bool:
    if not path.is_file():
        return False
    if path.name in RELEASE_EXCLUDED_NAMES:
        return False
    if _has_part(path, root, SOURCE_SCAN_EXCLUDED_PARTS):
        return False
    if path.suffix.lower() in TRANSIENT_SUFFIXES:
        return False
    return True


def include_in_release_manifest(path: Path, root: Path) -> bool:
    return is_project_source(path, root)
