"""Polígonos regulares: radios, orientación, huecos y rollback."""

import math
from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.service import CADService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "tuerca_hexagonal.iacs"


def test_polygon_hex_nut_extrudes_exports_and_regenerates(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/tuerca.iacad", "Tuerca hexagonal")
    made = cad.execute_script("parts/tuerca.iacad", EXAMPLE.read_text(encoding="utf-8"))
    expected = (150 * math.sqrt(3) - 16 * math.pi) * 6
    assert made["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    assert made["summary"]["bounds_mm"]["principal"] == {
        "min": [-10, -8.660254, 0], "max": [10, 8.660254, 6]
    }
    assert made["checks"]["passed"] == 1
    assert CADService(root=tmp_path).validate("parts/tuerca.iacad")["cache"] == {"hits": 1, "misses": 0}
    cad.export("parts/tuerca.iacad", "step", "out/tuerca.step")
    solid = import_step(tmp_path / "out/tuerca.step")
    assert solid.is_valid and solid.volume == pytest.approx(expected, abs=1e-5)

    modified = cad.execute("parts/tuerca.iacad", [
        {"cmd": "param.set", "args": {"name": "radio", "value": "12 mm"}},
        {"cmd": "param.set", "args": {"name": "giro", "value": "30 deg"}},
    ])
    assert modified["summary"]["volume_mm3"] == pytest.approx(
        (216 * math.sqrt(3) - 16 * math.pi) * 6, abs=1e-5
    )
    assert modified["cache"] == {"hits": 0, "misses": 1}
    assert cad.navigate("parts/tuerca.iacad", "undo")["summary"]["volume_mm3"] == pytest.approx(expected)


def test_polygon_inradius_yz_offset_plane(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Cuadrado en YZ")
    result = cad.execute("p.iacad", [
        {"cmd": "sketch.new", "args": {"id": "perfil", "plane": "YZ", "offset": 2}},
        {"cmd": "sketch.polygon", "args": {"sketch": "perfil", "id": "exterior", "center": [5, 7],
                                        "side_count": 4, "radius": 5, "radius_type": "inradius",
                                        "angle": "45 deg"}},
        {"cmd": "feature.extrude", "args": {"id": "prisma", "profile": "perfil", "body": "principal",
                                        "extent": {"distance": 3}}},
    ])
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [2, 0, 2], "max": [5, 10, 12]}
    assert result["summary"]["volume_mm3"] == pytest.approx(300)


def test_polygon_can_cut_hole_in_rectangle(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Alojamiento hexagonal")
    result = cad.execute("p.iacad", [
        {"cmd": "sketch.new", "args": {"id": "perfil", "plane": "XY"}},
        {"cmd": "sketch.rectangle", "args": {"sketch": "perfil", "id": "exterior", "center": [20, 20],
                                           "width": 40, "height": 40}},
        {"cmd": "sketch.polygon", "args": {"sketch": "perfil", "id": "alojamiento", "center": [20, 20],
                                        "side_count": 6, "radius": 5}},
        {"cmd": "feature.extrude", "args": {"id": "placa", "profile": "perfil", "body": "principal",
                                        "extent": {"distance": 4}}},
    ])
    assert result["summary"]["volume_mm3"] == pytest.approx((1600 - 37.5 * math.sqrt(3)) * 4)


@pytest.mark.parametrize(("polygon", "code"), [
    ({"side_count": 2, "radius": 5}, "INVALID_ARGUMENT"),
    ({"side_count": 65, "radius": 5}, "INVALID_ARGUMENT"),
    ({"side_count": 3.5, "radius": 5}, "INVALID_ARGUMENT"),
    ({"side_count": 6, "radius": 0}, "INVALID_DIMENSION"),
    ({"side_count": 6, "radius": "3 deg"}, "UNIT_MISMATCH"),
    ({"side_count": 6, "radius": 5, "angle": "2 mm"}, "UNIT_MISMATCH"),
    ({"side_count": 6, "radius": 5, "radius_type": "other"}, "INVALID_ARGUMENT"),
    ({"side_count": 6, "radius": 10, "center": [45, 45]}, "PROFILE_INVALID"),
])
def test_invalid_polygon_rolls_back(tmp_path, polygon, code):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Polígono inválido")
    cad.execute("p.iacad", [
        {"cmd": "sketch.new", "args": {"id": "perfil", "plane": "XY"}},
        {"cmd": "sketch.rectangle", "args": {"sketch": "perfil", "id": "exterior", "center": [20, 20],
                                           "width": 40, "height": 40}},
    ])
    before = (tmp_path / "p.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [{"cmd": "sketch.polygon", "args": {
            "sketch": "perfil", "id": "hueco", "center": [20, 20], **polygon,
        }}])
    assert error.value.code == code
    assert (tmp_path / "p.iacad").read_bytes() == before
