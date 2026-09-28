"""Ranuras cerradas parametrizadas, huecos, planos y validación transaccional."""

import math
from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.service import CADService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "placa_ranura.iacs"


def test_slot_hole_extrudes_and_regenerates_after_parameter_change(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/ranura.iacad", "Placa con ranura")
    result = cad.execute_script("parts/ranura.iacad", EXAMPLE.read_text(encoding="utf-8"))
    expected = (60 * 30 - (24 - 6) * 6 - math.pi * 3**2) * 5
    assert result["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [0, 0, 0], "max": [60, 30, 5]}
    assert result["checks"]["passed"] == 1
    assert CADService(root=tmp_path).validate("parts/ranura.iacad")["cache"] == {"hits": 1, "misses": 0}
    cad.export("parts/ranura.iacad", "step", "out/ranura.step")
    solid = import_step(tmp_path / "out/ranura.step")
    assert solid.is_valid and solid.volume == pytest.approx(expected, abs=1e-5)

    modified = cad.execute("parts/ranura.iacad", [
        {"cmd": "param.set", "args": {"name": "ranura_l", "value": "28 mm"}},
        {"cmd": "param.set", "args": {"name": "giro", "value": "90 deg"}},
    ])
    assert modified["summary"]["volume_mm3"] == pytest.approx(
        (60 * 30 - (28 - 6) * 6 - math.pi * 3**2) * 5, abs=1e-5
    )
    assert modified["cache"] == {"hits": 0, "misses": 1}
    assert cad.navigate("parts/ranura.iacad", "undo")["summary"]["volume_mm3"] == pytest.approx(expected)


def test_slot_as_outer_profile_on_offset_xz_plane(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("pieza.iacad", "Perfil de ranura")
    created = cad.execute("pieza.iacad", [
        {"cmd": "sketch.new", "args": {"id": "perfil", "plane": "XZ", "offset": "5 mm"}},
        {"cmd": "sketch.slot", "args": {"sketch": "perfil", "id": "exterior", "center": [7, 9],
                                     "length": "18 mm", "width": "4 mm", "angle": "90 deg"}},
        {"cmd": "feature.extrude", "args": {"id": "cuerpo", "profile": "perfil",
                                        "extent": {"distance": "8 mm"}, "body": "principal"}},
    ])
    assert created["summary"]["bounds_mm"]["principal"] == {"min": [5, -13, 0], "max": [9, -5, 18]}
    assert created["summary"]["volume_mm3"] == pytest.approx(((18 - 4) * 4 + math.pi * 2**2) * 8)


@pytest.mark.parametrize(("slot", "code"), [
    ({"length": 6, "width": 6}, "INVALID_DIMENSION"),
    ({"length": 5, "width": 6}, "INVALID_DIMENSION"),
    ({"length": 20, "width": -2}, "INVALID_DIMENSION"),
    ({"length": 20, "width": 4, "angle": "3 mm"}, "UNIT_MISMATCH"),
    ({"length": 24, "width": 6, "center": [55, 15]}, "PROFILE_INVALID"),
])
def test_invalid_slot_does_not_change_document(tmp_path, slot, code):
    cad = CADService(root=tmp_path)
    cad.new("pieza.iacad", "Ranura inválida")
    cad.execute("pieza.iacad", [
        {"cmd": "sketch.new", "args": {"id": "perfil", "plane": "XY"}},
        {"cmd": "sketch.rectangle", "args": {"sketch": "perfil", "id": "exterior", "center": [30, 15],
                                           "width": 60, "height": 30}},
    ])
    before = (tmp_path / "pieza.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("pieza.iacad", [{"cmd": "sketch.slot", "args": {"sketch": "perfil", "id": "hueco", **slot}}])
    assert error.value.code == code
    assert (tmp_path / "pieza.iacad").read_bytes() == before
