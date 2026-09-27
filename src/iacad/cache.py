"""Caché descartable de B-Rep exacto, identificada por geometría y versión del kernel."""

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

import build123d
from build123d import Shape, export_brep, import_brep

from iacad import __version__
from iacad.storage import atomic_write

CACHE_VERSION = 1
logger = logging.getLogger(__name__)


class GeometryCache:
    def __init__(self, root: Path, *, writable: bool = True):
        self.root = root / ".iacad" / "cache"
        self.writable = writable
        self.hits = 0
        self.misses = 0

    def key(self, definition: dict) -> str:
        data = {
            "cache_version": CACHE_VERSION,
            "iacad": __version__,
            "kernel": build123d.__version__,
            "geometry": definition,
        }
        source = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    def path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.brep"

    @staticmethod
    def _checksum(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(block)
        return hasher.hexdigest()

    def _integrity_ok(self, path: Path) -> bool:
        try:
            return path.with_suffix(".sha256").read_text(encoding="ascii").strip() == self._checksum(path)
        except (OSError, UnicodeError):
            return False

    @staticmethod
    def _valid(shape: Shape) -> bool:
        return shape.is_valid and len(shape.solids()) == 1 and shape.volume > 0

    def get_or_build(self, definition: dict, build: Callable[[], Shape]) -> tuple[Shape, str]:
        key = self.key(definition)
        path = self.path(key)
        if path.is_file() and self._integrity_ok(path):
            try:
                shape = import_brep(path)
                if self._valid(shape):
                    self.hits += 1
                    return shape, key
            except Exception:
                # Archivos truncados, versiones viejas o cierres abruptos: la caché es derivada.
                logger.exception("No se pudo leer B-Rep de caché %s; regenerando", path)
        self.misses += 1
        shape = build()
        if self._valid(shape) and self.writable:
            self._save(path, shape)
        return shape, key

    @staticmethod
    def _save(path: Path, shape: Shape) -> None:
        temp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".brep", delete=False) as handle:
                temp = Path(handle.name)
            if not export_brep(shape, temp):
                return
            os.replace(temp, path)
            atomic_write(path.with_suffix(".sha256"), (GeometryCache._checksum(path) + "\n").encode("ascii"))
        except OSError:
            # Falta de espacio o acceso al directorio no debe invalidar el diseño CAD.
            pass
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
