"""Taladros con eje 3D, profundidad y perfil pasante dinámico."""

import math
from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.service import CADService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "placa_taladros.iacs"


def _hole(**changes):
    return {"cmd": "feature.hole", "args": {
        "id": "taladro", "target": "principal", "diameter": "8 mm",
        "axis": {"origin": [15, 15, 10], "dir": [0, 0, -1]}, **changes,
    }}


def test_through_and_blind_holes_export_step_and_regenerate(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/placa.iacad", "Placa taladrada")
    made = cad.execute_script("parts/placa.iacad", EXAMPLE.read_text(encoding="utf-8"), expected_revision=0)
    expected = 60 * 30 * 10 - math.pi * 4**2 * (10 + 4)
    assert made["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    assert made["summary"]["bounds_mm"]["principal"] == {"min": [0, 0, 0], "max": [60, 30, 10]}
    assert made["summary"]["bodies"] == 1 and made["checks"]["passed"] == 1
    assert made["cache"] == {"hits": 0, "misses": 3}
    assert CADService(root=tmp_path).validate("parts/placa.iacad")["cache"] == {"hits": 3, "misses": 0}
    faces = cad.query("parts/placa.iacad", "topology", body="principal", kind="face")["items"]
    assert len([face for face in faces if face["geom_type"] == "CYLINDER"]) == 2
    assert any(face["geom_type"] == "PLANE" and face["center_mm"] == [45, 15, 6] for face in faces)
    assert all(face["ref"] is None for face in faces)
    cad.export("parts/placa.iacad", "step", "out/placa.step")
    imported = import_step(tmp_path / "out/placa.step")
    assert imported.is_valid and imported.volume == pytest.approx(expected, rel=1e-7)

    changed = cad.execute("parts/placa.iacad", [
        {"cmd": "param.set", "args": {"name": "diametro", "value": "10 mm"}},
        {"cmd": "param.set", "args": {"name": "profundidad", "value": "6 mm"}},
    ])
    assert changed["summary"]["volume_mm3"] == pytest.approx(18_000 - 25 * math.pi * 16, abs=1e-5)
    assert changed["cache"] == {"hits": 1, "misses": 2}
    assert cad.navigate("parts/placa.iacad", "undo")["summary"]["volume_mm3"] == pytest.approx(expected)
    thicker = cad.execute("parts/placa.iacad", [
        {"cmd": "param.set", "args": {"name": "espesor", "value": "15 mm"}},
    ])
    assert thicker["summary"]["volume_mm3"] == pytest.approx(27_000 - 16 * math.pi * (15 + 4), abs=1e-5)
    assert thicker["summary"]["bounds_mm"]["principal"]["max"] == [60, 30, 15]
    assert thicker["cache"] == {"hits": 0, "misses": 3}


@pytest.mark.parametrize(("origin", "direction"), [
    ([0, 5, 5], [2, 0, 0]),
    ([10, 5, 5], [-3, 0, 0]),
])
def test_through_hole_uses_full_body_extent_along_axis(tmp_path, origin, direction):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Taladro horizontal")
    made = cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 20, "width": 20, "height": 10}},
        _hole(diameter=4, axis={"origin": origin, "dir": direction}),
    ])
    assert made["summary"]["volume_mm3"] == pytest.approx(4000 - math.pi * 2**2 * 20, abs=1e-5)
    assert made["summary"]["bounds_mm"]["principal"] == {"min": [0, 0, 0], "max": [20, 20, 10]}


def test_blind_hole_on_side_has_exact_depth(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Taladro lateral ciego")
    made = cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 20, "width": 20, "height": 10}},
        _hole(diameter=4, axis={"origin": [20, 15, 5], "dir": [-3, 0, 0]}, mode="blind", depth=6),
    ])
    assert made["summary"]["volume_mm3"] == pytest.approx(4000 - math.pi * 2**2 * 6, abs=1e-5)
    faces = cad.query("p.iacad", "topology", body="principal", kind="face")["items"]
    assert any(face["geom_type"] == "PLANE" and face["center_mm"] == [14, 15, 5] for face in faces)


@pytest.mark.parametrize(("changes", "code"), [
    ({"diameter": 0}, "INVALID_DIMENSION"),
    ({"diameter": "1 deg"}, "UNIT_MISMATCH"),
    ({"mode": "blind"}, "INVALID_ARGUMENT"),
    ({"mode": "through", "depth": "5 mm"}, "INVALID_ARGUMENT"),
    ({"mode": "blind", "depth": 0}, "INVALID_DIMENSION"),
    ({"mode": "blind", "depth": "10 deg"}, "UNIT_MISMATCH"),
    ({"axis": {"origin": [0, 0, 0], "dir": [0, 0, 0]}}, "INVALID_ARGUMENT"),
    ({"axis": {"origin": [0, 0, "5 deg"], "dir": [0, 0, 1]}}, "UNIT_MISMATCH"),
    ({"axis": {"origin": [100, 100, 10], "dir": [0, 0, -1]}}, "HOLE_NO_EFFECT"),
    ({"axis": {"origin": [30, 15, 10], "dir": [0, 0, -1]}, "diameter": 35}, "HOLE_FAILED"),
    ({"target": "no_existe"}, "UNKNOWN_BODY"),
    ({"id": "base"}, "DUPLICATE_ID"),
])
def test_hole_bad_input_rolls_back(tmp_path, changes, code):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Taladro inválido")
    cad.execute("p.iacad", [{"cmd": "feature.box", "args": {"id": "base", "body": "principal",
                                                      "length": 60, "width": 30, "height": 10}}])
    before = (tmp_path / "p.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [_hole(**changes)], expected_revision=1)
    assert error.value.code == code
    assert (tmp_path / "p.iacad").read_bytes() == before
    dry_run = cad.execute("p.iacad", [_hole()], dry_run=True, expected_revision=1)
    assert dry_run["summary"]["volume_mm3"] == pytest.approx(18_000 - 160 * math.pi, abs=1e-5)
    assert (tmp_path / "p.iacad").read_bytes() == before
