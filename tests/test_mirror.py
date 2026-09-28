"""Espejo de cuerpo exacto sobre plano global, caché, rollback y exportación."""

from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.service import CADService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "placa_simetrica.iacs"


def _mirror(**changes):
    return {"cmd": "feature.mirror", "args": {
        "id": "espejo", "source": "principal", "body": "reflejado",
        "plane": {"origin": [0, 0, 0], "normal": [1, 0, 0]}, **changes,
    }}


def test_symmetric_plate_example_roundtrip_step_and_parameter_change(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/placa.iacad", "Placa simétrica")
    result = cad.execute_script("parts/placa.iacad", EXAMPLE.read_text(encoding="utf-8"))
    # Media placa: 20×6 + 8×(15−6) = 192 mm². Dos mitades, espesor 4 mm.
    assert result["summary"]["volume_mm3"] == pytest.approx(1536)
    assert result["summary"]["bounds_mm"]["principal"] == {
        "min": [-20, 0, 0], "max": [20, 15, 4],
    }
    assert result["summary"]["bodies"] == 1 and result["checks"]["passed"] == 1
    assert result["cache"] == {"hits": 0, "misses": 3}
    assert CADService(root=tmp_path).validate("parts/placa.iacad")["cache"] == {"hits": 3, "misses": 0}
    cad.export("parts/placa.iacad", "step", "out/placa.step")
    solid = import_step(tmp_path / "out/placa.step")
    assert solid.is_valid and solid.volume == pytest.approx(1536, abs=1e-5)

    changed = cad.execute("parts/placa.iacad", [
        {"cmd": "param.set", "args": {"name": "tramo", "value": "25 mm"}},
    ])
    assert changed["summary"]["volume_mm3"] == pytest.approx(1776)
    assert changed["summary"]["bounds_mm"]["principal"] == {
        "min": [-25, 0, 0], "max": [25, 15, 4],
    }
    assert changed["cache"] == {"hits": 0, "misses": 3}
    assert cad.navigate("parts/placa.iacad", "undo")["summary"]["volume_mm3"] == pytest.approx(1536)


def test_mirror_creates_independent_body_on_offset_plane_and_recomputes(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Copia reflejada")
    result = cad.execute("p.iacad", [
        {"cmd": "param.set", "args": {"name": "eje", "value": "0 mm"}},
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "origin": [10, 2, 0],
                                        "length": 5, "width": 4, "height": 3}},
        _mirror(plane={"origin": [0, "eje", 0], "normal": [0, 2, 0]}),
    ])
    assert result["summary"]["bodies"] == 2
    assert result["summary"]["bounds_mm"] == {
        "principal": {"min": [10, 2, 0], "max": [15, 6, 3]},
        "reflejado": {"min": [10, -6, 0], "max": [15, -2, 3]},
    }
    faces = cad.query("p.iacad", "topology", body="reflejado", kind="face")["items"]
    assert all(face["ref"] is None for face in faces)
    original_faces = cad.query("p.iacad", "topology", body="principal", kind="face")["items"]
    assert "@base/face:xmin" in {face["ref"] for face in original_faces}
    with pytest.raises(CadError) as error:
        cad.export("p.iacad", "step", "out/dos_cuerpos.step")
    assert error.value.code == "EXPORT_REQUIRES_SINGLE_BODY"

    moved = cad.execute("p.iacad", [{"cmd": "param.set", "args": {"name": "eje", "value": "10 mm"}}])
    assert moved["summary"]["bounds_mm"]["reflejado"] == {"min": [10, 14, 0], "max": [15, 18, 3]}
    assert moved["cache"] == {"hits": 1, "misses": 1}
    undone = cad.navigate("p.iacad", "undo")
    assert undone["summary"]["bounds_mm"]["reflejado"]["min"] == [10, -6, 0]


def test_joining_mirror_does_not_attribute_new_faces_to_original_box(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Caja simétrica")
    result = cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 10,
                                        "width": 6, "height": 4}},
        _mirror(),
        {"cmd": "feature.boolean", "args": {"id": "union", "op": "union", "target": "principal",
                                           "tools": ["reflejado"]}},
    ])
    assert result["summary"]["volume_mm3"] == pytest.approx(480)
    refs = {face["ref"] for face in cad.query("p.iacad", "topology", body="principal", kind="face")["items"]}
    assert "@base/face:xmin" not in refs
    assert refs == {None}


@pytest.mark.parametrize(("changes", "code"), [
    ({"plane": {"origin": [0, 0, 0], "normal": [0, 0, 0]}}, "INVALID_ARGUMENT"),
    ({"plane": {"origin": [0, 0, 0], "normal": [float("inf"), 0, 0]}}, "INVALID_ARGUMENT"),
    ({"plane": {"origin": [0, 0, 0], "normal": [1, 0]}}, "INVALID_ARGUMENT"),
    ({"plane": {"origin": ["90 deg", 0, 0], "normal": [1, 0, 0]}}, "UNIT_MISMATCH"),
    ({"source": "inexistente"}, "UNKNOWN_BODY"),
    ({"body": "principal"}, "INVALID_ARGUMENT"),
    ({"body": "ocupado"}, "DUPLICATE_ID"),
    ({"id": "base"}, "DUPLICATE_ID"),
])
def test_invalid_mirror_rolls_back(tmp_path, changes, code):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Plano inválido")
    cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal",
                                        "length": 10, "width": 10, "height": 5}},
        {"cmd": "feature.cylinder", "args": {"id": "auxiliar", "body": "ocupado",
                                             "radius": 2, "height": 5}},
    ])
    before = (tmp_path / "p.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [_mirror(**changes)], expected_revision=1)
    assert error.value.code == code
    assert (tmp_path / "p.iacad").read_bytes() == before
    dry = cad.execute("p.iacad", [_mirror()], dry_run=True, expected_revision=1)
    assert dry["summary"]["bodies"] == 3
    assert (tmp_path / "p.iacad").read_bytes() == before
