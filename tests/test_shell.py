"""Cascarones paramétricos: selección de caras, caché y rollback de OCCT."""

import math
from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.scripts import parse_script
from iacad.service import CADService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "caja_vaciada.iacs"


def test_inward_box_shell_example_export_parameter_edit_and_undo(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("caja.iacad", "Caja vaciada")
    result = cad.execute_script("caja.iacad", EXAMPLE.read_text(encoding="utf-8"), expected_revision=0)
    assert result["summary"]["valid"]
    assert result["summary"]["volume_mm3"] == pytest.approx(40 * 30 * 20 - 36 * 26 * 18)
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [0, 0, 0], "max": [40, 30, 20]}
    assert result["cache"] == {"hits": 0, "misses": 2}
    assert result["checks"]["passed"] == 1
    refs = {item["ref"] for item in cad.query("caja.iacad", "topology", kind="face")["items"]}
    assert refs == {None}  # Ni el aro de la abertura ni las paredes reciben nombres de la tapa borrada.
    assert cad.validate("caja.iacad")["cache"] == {"hits": 2, "misses": 0}

    cad.export("caja.iacad", "step", "out/caja.step")
    imported = import_step(tmp_path / "out/caja.step")
    assert imported.is_valid and imported.volume == pytest.approx(7152, rel=1e-7)

    changed = cad.execute("caja.iacad", [{"cmd": "param.set", "args": {"name": "espesor", "value": "3 mm"}}])
    assert changed["summary"]["volume_mm3"] == pytest.approx(40 * 30 * 20 - 34 * 24 * 17)
    assert changed["cache"] == {"hits": 1, "misses": 1}
    undo = CADService(root=tmp_path).navigate("caja.iacad", "undo", expected_revision=2)
    assert undo["summary"]["volume_mm3"] == result["summary"]["volume_mm3"]
    assert undo["cache"] == {"hits": 2, "misses": 0}


def test_outward_shell_does_not_relabel_offset_faces_as_original(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Vaciado exterior")
    result = cad.execute("p.iacad", [
        {"cmd": "param.set", "args": {"name": "pared", "value": "2 mm"}},
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 40, "width": 30, "height": 20}},
        {"cmd": "feature.shell", "args": {"id": "vaciado", "target": "principal", "thickness": "pared",
                                              "direction": "outward", "remove_faces": {
                                                  "refs": ["@base/face:zmax"], "expect": "one"}}},
    ])
    assert result["summary"]["valid"] and result["summary"]["volume_mm3"] > 40 * 30 * 20 - 36 * 26 * 18
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [-2, -2, -2], "max": [42, 32, 20]}
    assert all(item["ref"] is None for item in cad.query("p.iacad", "topology", kind="face")["items"])
    changed = cad.execute("p.iacad", [{"cmd": "param.set", "args": {"name": "pared", "value": "3 mm"}}])
    assert changed["cache"] == {"hits": 1, "misses": 1}
    assert changed["summary"]["bounds_mm"]["principal"] == {"min": [-3, -3, -3], "max": [43, 33, 20]}
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [{"cmd": "feature.shell", "args": {"id": "otra", "target": "principal", "thickness": 1,
                                                               "remove_faces": {"refs": ["@base/face:zmin"], "expect": "one"}}}])
    assert error.value.code == "REF_LOST"


def test_query_selection_and_multiple_open_faces(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Caja con dos aberturas")
    script = (
        "feature.box id=base body=principal length=40mm width=30mm height=20mm\n"
        "feature.shell id=vaciado target=principal remove_faces='?principal/faces[+Z]' expect=one thickness=2mm\n"
    )
    parsed = parse_script(script)
    assert parsed[1]["args"]["remove_faces"] == {"query": {"scope": "principal", "kind": "face", "where": "+Z"}, "expect": "one"}
    result = cad.execute("p.iacad", parsed)
    assert result["summary"]["volume_mm3"] == pytest.approx(7152)
    cad.new("doble.iacad", "Dos caras abiertas")
    result = cad.execute("doble.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 40, "width": 30, "height": 20}},
        {"cmd": "feature.shell", "args": {"id": "vaciado", "target": "principal", "thickness": 2,
                                              "remove_faces": {"refs": ["@base/face:zmax", "@base/face:xmax"], "expect": 2}}},
    ])
    assert result["summary"]["valid"] and 0 < result["summary"]["volume_mm3"] < 24_000


def test_inward_cylinder_shell_with_named_top_face(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("vaso.iacad", "Vaso cilíndrico")
    result = cad.execute("vaso.iacad", [
        {"cmd": "feature.cylinder", "args": {"id": "cilindro", "body": "principal", "radius": 10, "height": 20}},
        {"cmd": "feature.shell", "args": {"id": "vaciado", "target": "principal", "thickness": 2,
                                              "remove_faces": {"refs": ["@cilindro/face:top"], "expect": "one"}}},
    ])
    assert result["summary"]["valid"]
    assert result["summary"]["volume_mm3"] == pytest.approx(math.pi * (10**2 * 20 - 8**2 * 18), abs=1e-5)
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [-10, -10, 0], "max": [10, 10, 20]}


def test_invalid_thickness_or_selection_never_commits(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Validar vaciado")
    cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 40, "width": 30, "height": 20}},
    ])
    before = (tmp_path / "p.iacad").read_bytes()
    valid = {"id": "vaciado", "target": "principal", "remove_faces": {"refs": ["@base/face:zmax"], "expect": "one"}, "thickness": 2}
    for changed, code in [
        ({"thickness": 0}, "INVALID_DIMENSION"),
        ({"thickness": -1}, "INVALID_DIMENSION"),
        ({"thickness": "2 deg"}, "UNIT_MISMATCH"),
        ({"thickness": 15}, "SHELL_FAILED"),
        ({"remove_faces": {"refs": ["@base/face:bottom"], "expect": "one"}}, "REF_LOST"),
        ({"remove_faces": {"query": {"scope": "principal", "kind": "face", "where": "%PLANE"}, "expect": "one"}}, "SELECTION_COUNT"),
        ({"remove_faces": {"refs": ["@base/edge:xmax&ymax"], "expect": "one"}}, "INVALID_SELECTION"),
        ({"remove_faces": {"refs": ["@base/face:zmax"]}}, "INVALID_ARGUMENT"),
    ]:
        with pytest.raises(CadError) as error:
            cad.execute("p.iacad", [{"cmd": "feature.shell", "args": {**valid, **changed}}], expected_revision=1)
        assert error.value.code == code
        assert (tmp_path / "p.iacad").read_bytes() == before
    result = cad.execute("p.iacad", [{"cmd": "feature.shell", "args": valid}], dry_run=True, expected_revision=1)
    assert result["summary"]["volume_mm3"] == 7152 and (tmp_path / "p.iacad").read_bytes() == before
