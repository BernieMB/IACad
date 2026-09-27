"""Almacenamiento atómico, rutas del workspace y journal JSONL."""

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock, Timeout
from pydantic import ValidationError

from iacad.errors import CadError
from iacad.model import DOCUMENT_ADAPTER, Document


def workspace() -> Path:
    return Path(os.environ.get("IACAD_WORKSPACE", os.getcwd())).resolve()


def safe_path(path: str | Path, root: Path | None = None) -> Path:
    root = (root or workspace()).resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise CadError("PATH_OUTSIDE_WORKSPACE", "La ruta está fuera del workspace", path=str(path))
    return resolved


def encode(document: Document) -> bytes:
    data = document.model_dump(mode="json", exclude_none=True)
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def load(path: Path) -> Document:
    try:
        return DOCUMENT_ADAPTER.validate_json(path.read_bytes())
    except FileNotFoundError as exc:
        raise CadError("DOC_NOT_FOUND", "No existe el documento", path=str(path)) from exc
    except (ValidationError, ValueError) as exc:
        raise CadError("INVALID_DOCUMENT", "Documento .iacad inválido o incompatible", path=str(path), hint=str(exc)) from exc


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".iacad-", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def append_journal(root: Path, event: dict) -> None:
    # El journal registra las operaciones, incluso las rechazadas, pero no los dry-runs.
    journal = root / "journal" / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def document_lock(root: Path, path: Path):
    """Impide escrituras concurrentes incluso entre procesos CLI distintos."""

    relative = path.relative_to(root).as_posix().encode("utf-8")
    name = hashlib.sha256(relative).hexdigest() + ".lock"
    lock_path = root / ".iacad" / "locks" / name
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(lock_path, timeout=30):
            yield
    except Timeout as exc:
        raise CadError("DOC_LOCKED", "El documento está siendo modificado por otro proceso", path=str(path)) from exc
