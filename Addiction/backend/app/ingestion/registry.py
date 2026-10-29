"""The corpus registry: which PDFs may be ingested, and safe resolution of their paths.

Authorized documents are exactly the entries of db/seed_data/papers.json. Any other PDF in data/papers is only
reported as 'unregistered'. File names are internal: they never appear in API responses.
"""
from dataclasses import dataclass
from pathlib import Path

from db.seed import load_papers


class UnsafePathError(Exception):
    """A file name or path that is not a plain regular file directly inside the papers folder."""


@dataclass(frozen=True)
class RegisteredPaper:
    paper_id: str
    file_name: str


def load_registry() -> list[RegisteredPaper]:
    return [RegisteredPaper(p["paper_id"], p["file_name"]) for p in load_papers() if p.get("file_name")]


def resolve_pdf(papers_dir: Path, file_name: str) -> Path:
    """The PDF path, or UnsafePathError. Only bare file names, regular files (no symlinks, no recursion),
    and a resolved path that stays inside the papers folder are accepted."""
    if (not file_name or file_name != Path(file_name).name or file_name in (".", "..")
            or "/" in file_name or "\\" in file_name or not file_name.lower().endswith(".pdf")):
        raise UnsafePathError("The registered file name is not a plain PDF file name.")
    folder = papers_dir.resolve()
    candidate = folder / file_name
    if candidate.is_symlink():
        raise UnsafePathError("Symbolic links are not ingested.")
    if not candidate.is_file():
        raise UnsafePathError("The file was not found in the papers folder.")
    if candidate.resolve().parent != folder:
        raise UnsafePathError("The file is outside the papers folder.")
    return candidate


def find_unregistered(papers_dir: Path, registry: list[RegisteredPaper]) -> list[str]:
    known = {entry.file_name for entry in registry}
    if not papers_dir.is_dir():
        return []
    return sorted(p.name for p in papers_dir.iterdir()
                  if p.is_file() and p.suffix.lower() == ".pdf" and p.name not in known)
