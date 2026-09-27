"""Orquestación compartida entre CLI y MCP; sin estado geométrico persistido."""

import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from iacad.cache import GeometryCache
from iacad.commands import apply, help_for
from iacad.errors import CadError
from iacad.history import append as append_history
from iacad.history import checkpoint as mark_checkpoint
from iacad.history import read as read_history
from iacad.history import save as save_history
from iacad.history import target_document
from iacad.kernel import KernelAdapter
from iacad.model import DOCUMENT_ADAPTER, Document, PartDocument, ProjectDocument, Units, now
from iacad.naming import origins, topology
from iacad.plugins import load_plugins
from iacad.render import render as render_image
from iacad.scripts import parse_script
from iacad.storage import (
    append_journal,
    atomic_write,
    digest,
    document_lock,
    encode,
    load,
    safe_path,
    workspace,
)
from iacad.units import QuantityEvaluator


class CADService:
    def __init__(self, root: Path | None = None):
        load_plugins()
        self.root = (root or workspace()).resolve()
        self.kernel = KernelAdapter()
        self._lock = threading.RLock()

    def _doc_path(self, path: str) -> Path:
        resolved = safe_path(path, self.root)
        if resolved.suffix != ".iacad":
            raise CadError("INVALID_PATH", "Los documentos deben terminar en .iacad", path=path)
        return resolved

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _journal(self, event: str, path: Path, **fields) -> None:
        append_journal(self.root, {"ts": datetime.now(UTC).isoformat(), "event": event, "doc": self._relative(path), **fields})

    def new(self, path: str, name: str, units: str = "mm", kind: str = "part") -> dict:
        location = self._doc_path(path)
        with self._lock, document_lock(self.root, location):
            if location.exists():
                raise CadError("DOC_EXISTS", "El documento ya existe", path=path)
            if kind not in ("part", "project"):
                raise CadError("UNKNOWN_DOCUMENT_KIND", f"Tipo de documento no implementado: {kind}")
            try:
                model = PartDocument if kind == "part" else ProjectDocument
                document = model(name=name, units=Units(length=units))
            except ValidationError as exc:
                raise CadError("INVALID_DOCUMENT", "Datos de pieza inválidos", hint=str(exc)) from exc
            content = encode(document)
            atomic_write(location, content)
            save_history(self.root, document, read_history(self.root, document)[0])
            self._journal("doc_new", location, revision=0, hash_after=digest(content))
            return {"ok": True, "doc": self._relative(location), "uid": document.uid, "kind": kind, "revision": 0}

    def execute(self, path: str, commands: list[dict], *, dry_run: bool = False, expected_revision: int | None = None) -> dict:
        location = self._doc_path(path)
        with self._lock, document_lock(self.root, location):
            original = load(location)
            if expected_revision is not None and original.revision != expected_revision:
                raise CadError("REVISION_CONFLICT", f"Revisión esperada {expected_revision}, actual {original.revision}", path=path, hint="Consulta el documento antes de reintentar")
            if not isinstance(commands, list) or not commands:
                raise CadError("EMPTY_SCRIPT", "Proporciona al menos un comando")
            draft = original.model_copy(deep=True)
            before = digest(location.read_bytes())
            changes: list[str] = []
            try:
                for index, command in enumerate(commands):
                    try:
                        changes.append(apply(draft, command))
                    except CadError as exc:
                        exc.path = f"commands[{index}]" + (f".{exc.path}" if exc.path else "")
                        raise
                # Pydantic revalida la copia mutada y los argumentos de las features.
                draft = DOCUMENT_ADAPTER.validate_python(draft.model_dump())
                summary, checks, cache_stats = self._inspect(location, draft, cache_writable=not dry_run)
            except (CadError, ValidationError) as exc:
                error = exc if isinstance(exc, CadError) else CadError("INVALID_DOCUMENT", "Documento inválido", hint=str(exc))
                if not dry_run:
                    self._journal("command", location, rev_before=original.revision, rev_after=original.revision, hash_before=before, status="rejected", commands=commands, error=error.as_dict())
                raise error
            if not dry_run:
                history, history_reset = read_history(self.root, original)
                if history_reset:
                    save_history(self.root, original, history)
                draft.revision += 1
                draft.metadata.modified = now()
                # Una edición externa que ocurra mientras se calcula la geometría no se pisa.
                if digest(location.read_bytes()) != before:
                    raise CadError("DOC_CHANGED", "El documento cambió mientras se ejecutaba la transacción", path=path)
                content = encode(draft)
                atomic_write(location, content)
                append_history(self.root, draft, history)
                self._journal("command", location, rev_before=original.revision, rev_after=draft.revision, hash_before=before, hash_after=digest(content), status="ok", commands=commands, changes=changes)
            return {"ok": True, "doc": self._relative(location), "revision": draft.revision, "dry_run": dry_run, "changes": {"added_or_updated": changes}, "summary": summary, "checks": checks, "cache": cache_stats, "warnings": ([{"code": "HISTORY_RESET", "message": "Edición externa: historial reiniciado desde el documento actual"}] if not dry_run and history_reset else [])}

    def history(self, path: str) -> dict:
        location = self._doc_path(path)
        document = load(location)
        state, reset = read_history(self.root, document)
        return {"ok": True, "doc": self._relative(location), "revision": document.revision, **state, "external_edit": reset}

    def checkpoint(self, path: str, name: str, expected_revision: int | None = None) -> dict:
        location = self._doc_path(path)
        with self._lock, document_lock(self.root, location):
            document = load(location)
            self._expected(document, expected_revision)
            state, reset = read_history(self.root, document)
            mark_checkpoint(state, name)
            save_history(self.root, document, state)
            self._journal("checkpoint", location, rev=document.revision, name=name, external_edit=reset)
            return {"ok": True, "doc": self._relative(location), "revision": document.revision, "checkpoint": name}

    def navigate(self, path: str, action: str, expected_revision: int | None = None, name: str = "") -> dict:
        location = self._doc_path(path)
        with self._lock, document_lock(self.root, location):
            current = load(location)
            self._expected(current, expected_revision)
            state, reset = read_history(self.root, current)
            if reset:
                raise CadError("HISTORY_CHANGED", "El documento ha sido editado fuera de IACad", hint="Haz un nuevo exec o checkpoint para adoptar el contenido actual")
            if action == "undo":
                cursor = state["cursor"] - 1
            elif action == "redo":
                cursor = state["cursor"] + 1
            elif action == "restore":
                if name not in state["checkpoints"]:
                    raise CadError("NO_CHECKPOINT", f"No existe el checkpoint: {name}")
                cursor = next((i for i, item in enumerate(state["states"]) if item["revision"] == state["checkpoints"][name]), -1)
            else:
                raise CadError("UNKNOWN_ACTION", f"Acción de historial no implementada: {action}")
            if not 0 <= cursor < len(state["states"]):
                raise CadError("NO_HISTORY", "No hay revisión disponible para esta operación")
            snapshot_revision = state["states"][cursor]["revision"]
            draft = target_document(self.root, current, state["states"][cursor])
            if draft.uid != current.uid:
                raise CadError("HISTORY_CORRUPT", "Identidad de documento diferente")
            draft.revision = current.revision + 1
            draft.metadata.modified = now()
            summary, checks, cache_stats = self._inspect(location, draft)
            content = encode(draft)
            atomic_write(location, content)
            state["cursor"] = cursor
            state["current_revision"] = draft.revision
            save_history(self.root, draft, state)
            self._journal(action, location, rev_before=current.revision, rev_after=draft.revision, source_revision=snapshot_revision, hash_after=digest(content))
            return {"ok": True, "doc": self._relative(location), "revision": draft.revision, "restored_revision": snapshot_revision, "summary": summary, "checks": checks, "cache": cache_stats}

    @staticmethod
    def _expected(document: PartDocument, revision: int | None) -> None:
        if revision is not None and revision != document.revision:
            raise CadError("REVISION_CONFLICT", f"Revisión esperada {revision}, actual {document.revision}")

    def execute_script(self, path: str, text: str, *, dry_run: bool = False, expected_revision: int | None = None) -> dict:
        return self.execute(path, parse_script(text), dry_run=dry_run, expected_revision=expected_revision)

    def validate(self, path: str) -> dict:
        location = self._doc_path(path)
        document = load(location)
        summary, checks, cache_stats = self._inspect(location, document)
        return {"ok": checks["failed"] == 0, "doc": path, "revision": document.revision, "summary": summary, "checks": checks, "cache": cache_stats}

    def query(self, path: str, what: str = "summary", *, body: str | None = None,
              kind: str = "all", limit: int = 100, cursor: int = 0) -> dict:
        location = self._doc_path(path)
        document = load(location)
        if what == "tree":
            if document.kind == "project":
                return {"ok": True, "doc": path, "revision": document.revision, "documents": [ref.model_dump() for ref in document.documents], "requirements": [req.model_dump() for req in document.brief.requirements]}
            return {"ok": True, "doc": path, "revision": document.revision, "features": [{"id": f.id, "type": f.type, "args": f.args} for f in document.features], "bodies": [b.id for b in document.bodies]}
        if what == "params":
            evaluator = QuantityEvaluator(document)
            return {"ok": True, "doc": path, "revision": document.revision,
                    "parameters_mm": evaluator.resolved(), "parameters_deg": evaluator.resolved_angles()}
        if what == "brief" and document.kind == "project":
            return {"ok": True, "doc": path, "revision": document.revision, "brief": document.brief.model_dump()}
        if what == "summary":
            return self.validate(path)
        if what == "topology":
            if document.kind != "part":
                raise CadError("WRONG_DOCUMENT_KIND", "La topología solo existe en piezas", path=path)
            cache = GeometryCache(self.root)
            bodies = self.kernel.regenerate(document, cache)
            return {"ok": True, "doc": path, "revision": document.revision, "cache": cache.stats(),
                    **topology(bodies, origins(document), body=body, kind=kind, limit=limit, cursor=cursor)}
        raise CadError("UNKNOWN_QUERY", f"Consulta no implementada: {what}", hint="Usa summary, tree, params, topology o brief (proyecto)")

    def export(self, path: str, fmt: str, out: str) -> dict:
        if fmt not in ("step", "stl", "glb", "3mf"):
            raise CadError("FORMAT_UNSUPPORTED", f"Formato todavía no implementado: {fmt}", hint="Usa step, stl, glb o 3mf")
        document_path = self._doc_path(path)
        output = safe_path(out, self.root)
        if output.suffix.lower() != f".{fmt}":
            raise CadError("INVALID_PATH", f"La salida debe terminar en .{fmt}", path=out)
        if output == document_path:
            raise CadError("INVALID_PATH", "No se puede sobrescribir el documento .iacad")
        document = load(document_path)
        if document.kind != "part":
            raise CadError("WRONG_DOCUMENT_KIND", "Solo se exportan piezas en este MVP", path=path)
        cache = GeometryCache(self.root)
        bodies = self.kernel.regenerate(document, cache)
        checks = self._checks(document, bodies)
        if checks["failed"]:
            raise CadError("CHECK_FAILED", "Hay checks de error incumplidos; corrige el diseño antes de exportar", hint="iacad validate <documento> devuelve sus IDs y resultados")
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".iacad-", suffix=f".{fmt}", dir=output.parent)
        os.close(fd)
        temporary = Path(temp_name)
        try:
            self.kernel.export(bodies, fmt, temporary)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        output_hash = digest(output.read_bytes())
        self._journal("export", document_path, rev=document.revision, format=fmt, file=self._relative(output), file_hash=output_hash, status="ok")
        return {"ok": True, "doc": path, "revision": document.revision, "format": fmt, "file": self._relative(output), "file_hash": output_hash, "cache": cache.stats()}

    def render(self, path: str, out: str, *, views: str = "iso", size: int = 768) -> dict:
        document_path = self._doc_path(path)
        output = safe_path(out, self.root)
        if output.suffix.lower() != ".png":
            raise CadError("INVALID_PATH", "La salida del render debe ser .png", path=out)
        document = load(document_path)
        if document.kind != "part":
            raise CadError("WRONG_DOCUMENT_KIND", "Solo se renderizan piezas", path=path)
        cache = GeometryCache(self.root)
        bodies = self.kernel.regenerate(document, cache)
        if len(bodies) != 1:
            raise CadError("RENDER_REQUIRES_SINGLE_BODY", "Se necesita exactamente un cuerpo")
        if views not in ("iso", "front", "top", "right", "four") or not 256 <= size <= 1024:
            raise CadError("INVALID_ARGUMENT", "Usa views=iso|front|top|right|four y size=256..1024")
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".iacad-", suffix=".png", dir=output.parent)
        os.close(fd)
        temporary = Path(temp_name)
        try:
            info = render_image(next(iter(bodies.values())), temporary, views=views, size=size)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        self._journal("render", document_path, rev=document.revision, file=self._relative(output), views=views)
        return {"ok": True, "doc": path, "revision": document.revision, "file": self._relative(output),
                "file_hash": digest(output.read_bytes()), "cache": cache.stats(), **info}

    def help(self, topic: str = "") -> dict:
        return {"ok": True, **help_for(topic)}

    def _inspect(self, location: Path, document: Document, *, cache_writable: bool = True) -> tuple[dict, dict, dict]:
        QuantityEvaluator(document).validate_parameters()
        cache = GeometryCache(self.root, writable=cache_writable)
        if document.kind == "project":
            self._validate_links(location, document)
            return (
                {"documents": len(document.documents), "requirements": len(document.brief.requirements), "references_valid": True},
                {"passed": 0, "failed": 0, "warnings": 0, "results": []},
                cache.stats(),
            )
        bodies = self.kernel.regenerate(document, cache)
        return self.kernel.summary(bodies), self._checks(document, bodies), cache.stats()

    def _validate_links(self, location: Path, project: ProjectDocument) -> None:
        linked: dict[str, PartDocument] = {}
        for ref in project.documents:
            if Path(ref.path).is_absolute() or ".." in Path(ref.path).parts:
                raise CadError("INVALID_REFERENCE", "Las referencias del proyecto deben ser relativas y estar dentro de su directorio", path=ref.path)
            target = safe_path(ref.path, location.parent)
            if target.suffix != ".iacad" or target == location:
                raise CadError("INVALID_REFERENCE", "La referencia debe apuntar a otra pieza .iacad", path=ref.path)
            try:
                document = load(target)
            except CadError as exc:
                raise CadError("BROKEN_DOC_REF", "La pieza enlazada no está disponible o es inválida", path=ref.path, hint=exc.code) from exc
            if document.kind != ref.kind or document.uid != ref.uid:
                raise CadError("DOC_REF_MISMATCH", "El UID o tipo de la pieza enlazada no coincide", path=ref.path)
            linked[ref.path] = document
        for requirement in project.brief.requirements:
            for verification in requirement.verified_by:
                path, sep, target = verification.partition("#")
                if not sep or path not in linked:
                    raise CadError("BROKEN_VERIFICATION", "El requisito debe referirse a una pieza enlazada", path=requirement.id)
                part = linked[path]
                exists = (
                    any(check.get("id") == target[6:] for check in part.checks)
                    if target.startswith("check:")
                    else any(feature.id == target for feature in part.features)
                )
                if not exists:
                    raise CadError("BROKEN_VERIFICATION", "El check o feature de verificación no existe", path=requirement.id)

    @staticmethod
    def _checks(document: PartDocument, bodies: dict) -> dict:
        evaluator = QuantityEvaluator(document)
        results = []
        for check in document.checks:
            try:
                args = check
                target = bodies[args["target"]]
                if args["type"] == "valid_solid":
                    passed = target.is_valid and len(target.solids()) == 1
                elif args["type"] == "bbox_max":
                    passed = all(size <= evaluator.length(limit) for size, limit in zip(target.bounding_box().size, args["value"], strict=True))
                elif args["type"] == "volume_min":
                    passed = target.volume >= evaluator.volume(args["value"])
                else:
                    raise CadError("CHECK_UNSUPPORTED", f"Check no implementado: {args['type']}")
            except (KeyError, TypeError, ValueError) as exc:
                raise CadError("INVALID_CHECK", "Check inválido", hint=str(exc)) from exc
            results.append({"id": args["id"], "passed": bool(passed), "severity": args.get("severity", "error")})
        return {"passed": sum(r["passed"] for r in results), "failed": sum(not r["passed"] and r["severity"] == "error" for r in results), "warnings": sum(not r["passed"] and r["severity"] == "warning" for r in results), "results": results}
