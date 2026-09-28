"""Patrón lineal de booleana con herramienta de cuerpo y paso parametrizado."""

import math
from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.service import CADService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "placa_patron_lineal.iacs"


def _plate_tool() -> list[dict]:
    return [
        {"cmd": "feature.box", "args": {"id": "placa", "body": "principal", "length": 60, "width": 20, "height": 5}},
        {"cmd": "feature.cylinder", "args": {"id": "broca", "body": "herramienta", "radius": 2, "height": 5,
                                               "origin": [10, 10, 0]}},
    ]


def _pattern(**changes) -> dict:
    return {"cmd": "feature.pattern_linear", "args": {
        "id": "taladros", "source": "herramienta", "target": "principal", "count": 4,
        "spacing": 12, "direction": [1, 0, 0], **changes,
    }}


def test_example_pattern_step_parameter_edit_and_history(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/placa.iacad", "Placa perforada")
    original = cad.execute_script("parts/placa.iacad", EXAMPLE.read_text(encoding="utf-8"), expected_revision=0)
    expected = 60 * 20 * 5 - 4 * math.pi * 2**2 * 5
    assert original["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    assert original["summary"]["bodies"] == 1 and original["checks"]["passed"] == 1
    assert original["cache"] == {"hits": 0, "misses": 3}
    assert CADService(root=tmp_path).validate("parts/placa.iacad")["cache"] == {"hits": 3, "misses": 0}
    faces = cad.query("parts/placa.iacad", "topology", kind="face")["items"]
    assert len([face for face in faces if face["geom_type"] == "CYLINDER"]) == 4
    assert all(face["ref"] is None for face in faces)
    cad.export("parts/placa.iacad", "step", "out/placa.step")
    imported = import_step(tmp_path / "out/placa.step")
    assert imported.is_valid and imported.volume == pytest.approx(expected, rel=1e-7)

    changed = cad.execute("parts/placa.iacad", [{"cmd": "param.set", "args": {"name": "paso", "value": "10 mm"}}])
    assert changed["cache"] == {"hits": 2, "misses": 1}
    assert changed["summary"]["volume_mm3"] == original["summary"]["volume_mm3"]
    centers = [entry["center_mm"][0] for entry in cad.query("parts/placa.iacad", "topology", kind="face")["items"]
               if entry["geom_type"] == "CYLINDER"]
    assert sorted(centers) == pytest.approx([10, 20, 30, 40], abs=1e-5)
    radius = cad.execute("parts/placa.iacad", [{"cmd": "param.set", "args": {"name": "radio", "value": "3 mm"}}])
    assert radius["cache"] == {"hits": 1, "misses": 2}
    assert radius["summary"]["volume_mm3"] == pytest.approx(6000 - 4 * math.pi * 3**2 * 5, abs=1e-5)
    undone = CADService(root=tmp_path).navigate("parts/placa.iacad", "undo", expected_revision=3)
    assert undone["summary"]["volume_mm3"] == original["summary"]["volume_mm3"]
    assert undone["cache"] == {"hits": 3, "misses": 0}


def test_joined_ribs_and_keep_tool_are_explicit(tmp_path):
    cad = CADService(root=tmp_path)
    for name, keep in (("ribs", False), ("keep", True)):
        cad.new(f"{name}.iacad", name)
        result = cad.execute(f"{name}.iacad", [
            {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 60, "width": 20, "height": 5}},
            {"cmd": "feature.box", "args": {"id": "rib", "body": "herramienta", "length": 4, "width": 4,
                                            "height": 3, "origin": [10, 8, 5]}},
            _pattern(op="join", keep_tool=keep),
        ])
        assert result["summary"]["valid"] and result["summary"]["bodies"] == (2 if keep else 1)
        assert result["summary"]["volume_mm3"] == 6000 + 4 * 4 * 4 * 3 + (4 * 4 * 3 if keep else 0)
        assert result["summary"]["bounds_mm"]["principal"] == {"min": [0, 0, 0], "max": [60, 20, 8]}
        refs = [face["ref"] for face in cad.query(f"{name}.iacad", "topology", kind="face")["items"]]
        if keep:
            assert "@rib/face:zmax" in refs
        assert "@base/face:zmax" not in refs


def test_pattern_bad_inputs_and_instances_rollback(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "P")
    cad.execute("p.iacad", _plate_tool())
    before = (tmp_path / "p.iacad").read_bytes()
    for change, code in [
        ({"spacing": 0}, "INVALID_DIMENSION"),
        ({"spacing": "1 deg"}, "UNIT_MISMATCH"),
        ({"spacing": 40}, "PATTERN_NO_EFFECT"),
        ({"direction": [0, 0, 1]}, "PATTERN_NO_EFFECT"),
        ({"direction": [0, 0, 0]}, "INVALID_ARGUMENT"),
        ({"direction": [1e308, 1e308, 1e308]}, "PATTERN_NO_EFFECT"),
        ({"count": 1}, "INVALID_ARGUMENT"),
        ({"count": 65}, "INVALID_ARGUMENT"),
        ({"source": "principal"}, "INVALID_ARGUMENT"),
        ({"source": "inexistente"}, "UNKNOWN_BODY"),
        ({"op": "join"}, "PATTERN_NO_EFFECT"),
    ]:
        with pytest.raises(CadError) as error:
            cad.execute("p.iacad", [_pattern(**change)], expected_revision=1)
        assert error.value.code == code
        assert (tmp_path / "p.iacad").read_bytes() == before
    dry = cad.execute("p.iacad", [_pattern()], expected_revision=1, dry_run=True)
    assert dry["summary"]["volume_mm3"] == pytest.approx(6000 - 80 * math.pi, abs=1e-5)
    assert (tmp_path / "p.iacad").read_bytes() == before


def test_disconnected_join_does_not_commit(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "P")
    cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 60, "width": 20, "height": 5}},
        {"cmd": "feature.box", "args": {"id": "extra", "body": "herramienta", "length": 2, "width": 2,
                                        "height": 2, "origin": [10, 10, 10]}},
    ])
    before = (tmp_path / "p.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [_pattern(op="join")])
    assert error.value.code == "PATTERN_DISCONNECTED"
    assert (tmp_path / "p.iacad").read_bytes() == before


def test_pattern_can_cut_with_tool_created_by_extrusion(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Pieza con herramienta desde croquis")
    result = cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "placa", "body": "principal", "length": 60, "width": 20, "height": 5}},
        {"cmd": "sketch.new", "args": {"id": "disco", "plane": "XY"}},
        {"cmd": "sketch.circle", "args": {"sketch": "disco", "id": "c", "center": [10, 10], "radius": 2}},
        {"cmd": "feature.extrude", "args": {"id": "broca", "profile": "disco", "extent": {"distance": 5},
                                        "body": "herramienta"}},
        _pattern(),
    ])
    assert result["summary"]["bodies"] == 1
    assert result["summary"]["volume_mm3"] == pytest.approx(6000 - 80 * math.pi, abs=1e-5)
