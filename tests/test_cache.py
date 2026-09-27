"""Regeneración incremental: B-Rep reutilizable en sesiones y procesos posteriores."""

import pytest

from iacad.service import CADService


def test_cache_only_invalidates_dependent_features(tmp_path):
    service = CADService(root=tmp_path)
    service.new("parts/placa.iacad", "Placa")
    result = service.execute("parts/placa.iacad", [
        {"cmd": "param.set", "args": {"name": "largo", "value": "40 mm"}},
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": "largo", "width": 30, "height": 6}},
        {"cmd": "feature.cylinder", "args": {"id": "broca", "body": "herramienta", "radius": 4, "height": 6, "origin": [20, 15, 0]}},
        {"cmd": "feature.boolean", "args": {"id": "corte", "op": "cut", "target": "principal", "tools": ["herramienta"]}},
    ])
    assert result["cache"] == {"hits": 0, "misses": 3}
    assert len(list((tmp_path / ".iacad/cache").rglob("*.brep"))) == 3
    restarted = CADService(root=tmp_path)
    assert restarted.validate("parts/placa.iacad")["cache"] == {"hits": 3, "misses": 0}

    changed = restarted.execute("parts/placa.iacad", [
        {"cmd": "param.set", "args": {"name": "largo", "value": "50 mm"}},
    ])
    assert changed["summary"]["bounds_mm"]["principal"]["max"][0] == 50
    assert changed["cache"] == {"hits": 1, "misses": 2}  # broca sin cambios
    assert restarted.validate("parts/placa.iacad")["cache"] == {"hits": 3, "misses": 0}


def test_dry_run_uses_but_does_not_create_cache_entries(tmp_path):
    service = CADService(root=tmp_path)
    service.new("p.iacad", "P")
    command = {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 5, "width": 5, "height": 5}}
    first = service.execute("p.iacad", [command], dry_run=True)
    assert first["cache"] == {"hits": 0, "misses": 1}
    assert not (tmp_path / ".iacad/cache").exists()
    service.execute("p.iacad", [command])
    path = next((tmp_path / ".iacad/cache").rglob("*.brep"))
    assert path.stat().st_size > 0
    assert path.with_suffix(".sha256").is_file()
    path.write_bytes(b"BRep corrupto")
    validated = service.validate("p.iacad")
    assert validated["cache"] == {"hits": 0, "misses": 1}
    assert validated["summary"]["volume_mm3"] == pytest.approx(125)
    assert path.stat().st_size > 50


def test_cache_key_includes_kernel_version(tmp_path, monkeypatch):
    import iacad.cache as cache_module

    service = CADService(root=tmp_path)
    service.new("p.iacad", "P")
    service.execute("p.iacad", [{"cmd": "feature.box", "args": {"id": "b", "body": "x", "length": 3, "width": 3, "height": 3}}])
    assert service.validate("p.iacad")["cache"]["hits"] == 1
    monkeypatch.setattr(cache_module.build123d, "__version__", "other-version")
    assert service.validate("p.iacad")["cache"] == {"hits": 0, "misses": 1}
