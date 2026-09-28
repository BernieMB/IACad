"""Patrón circular exacto de una herramienta, con eje global y ángulo paramétrico."""

import math
from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.service import CADService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "brida_patron_circular.iacs"


def _base():
    return [
        {"cmd": "feature.box", "args": {"id": "placa", "body": "principal", "length": 50, "width": 50,
                                        "height": 5, "origin": [-25, -25, 0]}},
        {"cmd": "feature.cylinder", "args": {"id": "broca", "body": "herramienta", "radius": 2,
                                             "height": 5, "origin": [15, 0, 0]}},
    ]


def _pattern(**kwargs):
    return {"cmd": "feature.pattern_circular", "args": {
        "id": "taladros", "source": "herramienta", "target": "principal", "count": 4,
        "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}, **kwargs,
    }}


def _centers(cad, path):
    return sorted(tuple(face["center_mm"][:2]) for face in cad.query(path, "topology", kind="face")["items"]
                  if face["geom_type"] == "CYLINDER")


def test_full_circle_script_roundtrip_cache_edit_and_undo(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("brida.iacad", "Brida")
    made = cad.execute_script("brida.iacad", EXAMPLE.read_text(encoding="utf-8"), expected_revision=0)
    expected = 50 * 50 * 5 - 4 * math.pi * 2**2 * 5
    assert made["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    assert made["checks"]["passed"] == 1 and made["summary"]["bodies"] == 1
    assert made["cache"] == {"hits": 0, "misses": 3}
    assert _centers(cad, "brida.iacad") == pytest.approx([(-15, 0), (0, -15), (0, 15), (15, 0)], abs=1e-5)
    assert all(item["ref"] is None for item in cad.query("brida.iacad", "topology", kind="face")["items"])
    assert cad.validate("brida.iacad")["cache"] == {"hits": 3, "misses": 0}
    cad.export("brida.iacad", "step", "out/brida.step")
    assert import_step(tmp_path / "out/brida.step").volume == pytest.approx(expected, rel=1e-7)

    moved = cad.execute("brida.iacad", [{"cmd": "param.set", "args": {"name": "radio_pernos", "value": "12 mm"}}])
    assert moved["cache"] == {"hits": 1, "misses": 2}
    assert _centers(cad, "brida.iacad") == pytest.approx([(-12, 0), (0, -12), (0, 12), (12, 0)], abs=1e-5)
    turned = cad.execute("brida.iacad", [{"cmd": "param.set", "args": {"name": "giro", "value": "180 deg"}}])
    assert turned["cache"] == {"hits": 2, "misses": 1}
    assert _centers(cad, "brida.iacad") == pytest.approx([(-12, 0), (-6, 10.392305), (6, 10.392305), (12, 0)], abs=1e-4)
    undone = CADService(root=tmp_path).navigate("brida.iacad", "undo", expected_revision=3)
    assert undone["cache"] == {"hits": 3, "misses": 0}
    assert _centers(cad, "brida.iacad") == pytest.approx([(-12, 0), (0, -12), (0, 12), (12, 0)], abs=1e-5)


def test_axis_offset_normalization_and_keep_tool(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Placa desplazada")
    result = cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "placa", "body": "principal", "length": 50, "width": 50,
                                        "height": 5, "origin": [5, 5, 0]}},
        {"cmd": "feature.cylinder", "args": {"id": "broca", "body": "herramienta", "radius": 2,
                                             "height": 5, "origin": [45, 30, 0]}},
        _pattern(axis={"origin": [30, 30, 0], "dir": [0, 0, 10]}, keep_tool=True),
    ])
    assert result["summary"]["bodies"] == 2 and result["summary"]["valid"]
    assert result["summary"]["volume_mm3"] == pytest.approx(12500 - 80 * math.pi + 20 * math.pi, abs=1e-5)
    tool = cad.query("p.iacad", "topology", body="herramienta", kind="face")
    assert "@broca/face:top" in {item["ref"] for item in tool["items"]}
    assert cad.query("p.iacad", "tree")["bodies"] == ["principal", "herramienta"]


def test_invalid_angle_axis_and_disconnected_instances_rollback(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "P")
    cad.execute("p.iacad", _base())
    before = (tmp_path / "p.iacad").read_bytes()
    for change, code in [
        ({"angle": 0}, "INVALID_ANGLE"),
        ({"angle": "361 deg"}, "INVALID_ANGLE"),
        ({"angle": "90 mm"}, "UNIT_MISMATCH"),
        ({"axis": {"dir": [0, 0, 0]}}, "INVALID_ARGUMENT"),
        ({"axis": {"dir": [1e308, 1e308, 1e308]}}, "PATTERN_NO_EFFECT"),
        ({"count": 1}, "INVALID_ARGUMENT"),
        ({"source": "principal"}, "INVALID_ARGUMENT"),
        ({"source": "ausente"}, "UNKNOWN_BODY"),
        ({"axis": {"origin": [30, 0, 0], "dir": [0, 0, 1]}}, "PATTERN_NO_EFFECT"),
    ]:
        try:
            cad.execute("p.iacad", [_pattern(**change)], expected_revision=1)
        except CadError as error:
            assert error.code == code, change
        else:
            pytest.fail(f"La entrada {change} debía fallar con {code}")
        assert (tmp_path / "p.iacad").read_bytes() == before
    dry = cad.execute("p.iacad", [_pattern()], expected_revision=1, dry_run=True)
    assert dry["summary"]["volume_mm3"] == pytest.approx(12500 - 80 * math.pi, abs=1e-5)
    assert (tmp_path / "p.iacad").read_bytes() == before


def test_join_around_axis_and_reject_isolated_tool(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("ribs.iacad", "Nervios")
    joined = cad.execute("ribs.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 50, "width": 50,
                                        "height": 5, "origin": [-25, -25, 0]}},
        {"cmd": "feature.box", "args": {"id": "nervio", "body": "herramienta", "length": 3, "width": 3,
                                        "height": 2, "origin": [14, -1.5, 5]}},
        _pattern(op="join"),
    ])
    assert joined["summary"]["valid"] and joined["summary"]["volume_mm3"] == pytest.approx(12500 + 72, abs=1e-5)

    cad.new("isolated.iacad", "Nervios separados")
    cad.execute("isolated.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 50, "width": 50,
                                        "height": 5, "origin": [-25, -25, 0]}},
        {"cmd": "feature.box", "args": {"id": "nervio", "body": "herramienta", "length": 3, "width": 3,
                                        "height": 2, "origin": [14, -1.5, 10]}},
    ])
    before = (tmp_path / "isolated.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("isolated.iacad", [_pattern(op="join")])
    assert error.value.code == "PATTERN_DISCONNECTED"
    assert (tmp_path / "isolated.iacad").read_bytes() == before
