"""Revisiones persistentes, undo/redo y checkpoints; el documento sigue siendo la fuente de verdad."""

import json
import re
from pathlib import Path

from iacad.errors import CadError
from iacad.model import Document
from iacad.storage import atomic_write, digest, encode, load


def design_hash(document: Document) -> str:
    """Huella del diseño independiente de revisión y timestamps (edición manual detectable)."""

    value = document.model_dump(mode="json", exclude_none=True)
    value.pop("revision", None)
    value["metadata"].pop("created", None)
    value["metadata"].pop("modified", None)
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=True).encode("utf-8"))


def directory(root: Path, document: Document) -> Path:
    return root / ".iacad" / "revisions" / document.uid


def state_path(root: Path, document: Document) -> Path:
    return directory(root, document) / "history.json"


def revision_path(root: Path, document: Document, revision: int, fingerprint: str) -> Path:
    # Distintos contenidos pueden compartir el mismo contador si alguien editó el JSON a mano.
    return directory(root, document) / f"{revision}-{fingerprint.removeprefix('sha256:')[:12]}.iacad"


def initial(document: Document) -> dict:
    return {
        "states": [{"revision": document.revision, "hash": design_hash(document)}],
        "cursor": 0,
        "current_revision": document.revision,
        "checkpoints": {},
    }


def read(root: Path, document: Document) -> tuple[dict, bool]:
    """Una edición manual o un commit interrumpido inicia una rama nueva conservando snapshots viejos."""

    path = state_path(root, document)
    if not path.exists():
        return initial(document), False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if (state["current_revision"] != document.revision or
            state["states"][state["cursor"]]["hash"] != design_hash(document)):
            return initial(document), True
        return state, False
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise CadError("HISTORY_CORRUPT", "Historial de revisiones inválido", path=str(path), hint=str(exc)) from exc


def save(root: Path, document: Document, state: dict) -> None:
    atomic_write(revision_path(root, document, document.revision, design_hash(document)), encode(document))
    atomic_write(state_path(root, document), (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def append(root: Path, document: Document, state: dict) -> None:
    active = state["cursor"] + 1
    state["states"] = state["states"][:active] + [{"revision": document.revision, "hash": design_hash(document)}]
    available = {item["revision"] for item in state["states"]}
    state["checkpoints"] = {name: rev for name, rev in state["checkpoints"].items() if rev in available}
    state["cursor"] = active
    state["current_revision"] = document.revision
    save(root, document, state)


def target_document(root: Path, document: Document, entry: dict) -> Document:
    path = revision_path(root, document, entry["revision"], entry["hash"])
    target = load(path)
    if target.uid != document.uid or design_hash(target) != entry["hash"]:
        raise CadError("HISTORY_CORRUPT", "Snapshot de otra revisión o documento", path=str(path))
    return target


def checkpoint(state: dict, name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name):
        raise CadError("INVALID_ARGUMENT", "Nombre de checkpoint inválido", path="name")
    state["checkpoints"][name] = state["states"][state["cursor"]]["revision"]
