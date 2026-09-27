"""Punto de extensión versionado (v1) mediante entry points de paquetes Python."""

from importlib.metadata import entry_points

from iacad.commands import register
from iacad.kernel import register_feature

_loaded = False


def load_plugins() -> None:
    global _loaded
    if _loaded:
        return
    for entry_point in entry_points(group="iacad.plugins"):
        # Cada distribución instalada es de confianza, como cualquier dependencia Python.
        entry_point.load()(register, register_feature)
    _loaded = True
