"""Croquis 2D XY/XZ/YZ, huecos, extrusión y rollback paramétrico."""

import math
import zipfile
from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.service import CADService

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_sketch_rectangle_hole_extrudes_and_exports_step(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/placa.iacad", "Placa croquis")
    result = cad.execute_script("parts/placa.iacad", (EXAMPLES / "placa_croquis.iacs").read_text(encoding="utf-8"))
    expected = 40 * 30 * 6 - math.pi * 4**2 * 6
    assert result["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [0, 0, 0], "max": [40, 30, 6]}
    assert result["checks"]["passed"] == 2
    assert result["cache"] == {"hits": 0, "misses": 1}
    assert CADService(root=tmp_path).validate("parts/placa.iacad")["cache"] == {"hits": 1, "misses": 0}
    cad.export("parts/placa.iacad", "step", "out/placa.step")
    solid = import_step(tmp_path / "out/placa.step")
    assert solid.is_valid and solid.volume == pytest.approx(expected, rel=1e-7)
    cad.export("parts/placa.iacad", "glb", "out/placa.glb")
    assert (tmp_path / "out/placa.glb").read_bytes()[:4] == b"glTF"
    cad.export("parts/placa.iacad", "3mf", "out/placa.3mf")
    with zipfile.ZipFile(tmp_path / "out/placa.3mf") as package:
        assert "[Content_Types].xml" in package.namelist()
        assert any(name.endswith(".model") for name in package.namelist())

    modified = cad.execute("parts/placa.iacad", [{"cmd": "param.set", "args": {"name": "radio", "value": "5 mm"}}])
    assert modified["cache"] == {"hits": 0, "misses": 1}
    assert modified["summary"]["volume_mm3"] == pytest.approx(40 * 30 * 6 - math.pi * 5**2 * 6)
    undone = cad.navigate("parts/placa.iacad", "undo")
    assert undone["cache"] == {"hits": 1, "misses": 0}
    assert undone["summary"]["volume_mm3"] == pytest.approx(expected)


def test_l_profile_xz_symmetric_uses_explicit_negative_y_normal(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/soporte.iacad", "Perfil L")
    result = cad.execute_script("parts/soporte.iacad", (EXAMPLES / "perfil_l.iacs").read_text(encoding="utf-8"))
    assert result["summary"]["volume_mm3"] == 25_000
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [0, -25, 0], "max": [50, 25, 55]}
    assert result["checks"]["passed"] == 1


def test_extrude_circle_along_yz_and_reverse_xy(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("yz.iacad", "Cilindro X")
    created = cad.execute("yz.iacad", [
        {"cmd": "sketch.new", "args": {"id": "seccion", "plane": "YZ"}},
        {"cmd": "sketch.circle", "args": {"sketch": "seccion", "id": "disco", "center": [10, 20], "radius": 3}},
        {"cmd": "feature.extrude", "args": {"id": "eje", "profile": "seccion", "extent": {"distance": 12}, "body": "principal"}},
    ])
    assert created["summary"]["bounds_mm"]["principal"] == {"min": [0, 7, 17], "max": [12, 13, 23]}
    cad.new("reverse.iacad", "Hacia abajo")
    reverse = cad.execute("reverse.iacad", [
        {"cmd": "sketch.new", "args": {"id": "seccion", "plane": "XY"}},
        {"cmd": "sketch.circle", "args": {"sketch": "seccion", "id": "disco", "center": [0, 0], "radius": 3}},
        {"cmd": "feature.extrude", "args": {"id": "eje", "profile": "seccion", "extent": {"distance": 12}, "direction": "reverse", "body": "principal"}},
    ])
    assert reverse["summary"]["bounds_mm"]["principal"] == {"min": [-3, -3, -12], "max": [3, 3, 0]}


def test_extruded_sketch_cut_and_invalid_profile_rolls_back(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "P")
    cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 40, "width": 30, "height": 6}},
        {"cmd": "sketch.new", "args": {"id": "taladro", "plane": "XY"}},
        {"cmd": "sketch.circle", "args": {"sketch": "taladro", "id": "c", "center": [20, 15], "radius": 4}},
        {"cmd": "feature.extrude", "args": {"id": "corte", "profile": "taladro", "extent": {"distance": 6}, "op": "cut", "target": "principal"}},
    ])
    expected = 40 * 30 * 6 - math.pi * 4**2 * 6
    assert cad.validate("p.iacad")["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    before = (tmp_path / "p.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [{"cmd": "sketch.circle", "args": {"sketch": "taladro", "id": "fuera", "center": [100, 100], "radius": 2}}])
    assert error.value.code == "PROFILE_INVALID"
    assert (tmp_path / "p.iacad").read_bytes() == before


def test_empty_sketch_is_editable_but_cannot_be_extruded(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "P")
    cad.execute("p.iacad", [{"cmd": "sketch.new", "args": {"id": "sin_perfil", "plane": "XZ"}}])
    before = (tmp_path / "p.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [{"cmd": "feature.extrude", "args": {"id": "e", "profile": "sin_perfil", "extent": {"distance": 5}, "body": "principal"}}])
    assert error.value.code == "PROFILE_INVALID"
    assert (tmp_path / "p.iacad").read_bytes() == before
