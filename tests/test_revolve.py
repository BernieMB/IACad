"""Revolución paramétrica: unidades angulares, cotas, booleanas y rollback."""

import math
from pathlib import Path

import pytest
from build123d import import_step
from PIL import Image

from iacad.errors import CadError
from iacad.model import Parameter, PartDocument, Units
from iacad.service import CADService
from iacad.units import QuantityEvaluator

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "casquillo_revolucion.iacs"


def test_tube_revolve_roundtrip_and_edit_angular_parameter(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/casquillo.iacad", "Casquillo")
    result = cad.execute_script("parts/casquillo.iacad", EXAMPLE.read_text(encoding="utf-8"), expected_revision=0)
    expected = math.pi * (10**2 - 5**2) * 20
    assert result["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [-10, 0, -10], "max": [10, 20, 10]}
    assert result["cache"] == {"hits": 0, "misses": 1}
    assert result["checks"]["passed"] == 1
    assert cad.query("parts/casquillo.iacad", "params")["parameters_deg"] == {"giro": 360.0}
    assert CADService(root=tmp_path).validate("parts/casquillo.iacad")["cache"] == {"hits": 1, "misses": 0}
    cad.export("parts/casquillo.iacad", "step", "out/casquillo.step")
    imported = import_step(tmp_path / "out/casquillo.step")
    assert imported.is_valid and imported.volume == pytest.approx(expected, rel=1e-7)
    preview = cad.render("parts/casquillo.iacad", "out/casquillo.png", views="four", size=512)
    assert preview["views"] == "four"
    with Image.open(tmp_path / "out/casquillo.png") as image:
        # La vista frontal (cuadrante superior derecho) debe mostrar el hueco pasante.
        assert image.getpixel((384, 128)) == (24, 30, 41)
        assert image.getpixel((450, 128)) != (24, 30, 41)

    changed = cad.execute("parts/casquillo.iacad", [
        {"cmd": "param.set", "args": {"name": "giro", "value": "90 deg"}},
    ])
    assert changed["cache"] == {"hits": 0, "misses": 1}
    assert cad.query("parts/casquillo.iacad", "params")["parameters_deg"] == {"giro": 90}
    assert changed["summary"]["volume_mm3"] == pytest.approx(expected / 4, abs=1e-5)
    restored = cad.navigate("parts/casquillo.iacad", "undo", expected_revision=2)
    assert restored["cache"] == {"hits": 1, "misses": 0}
    assert restored["summary"]["volume_mm3"] == result["summary"]["volume_mm3"]


def test_angular_units_distinguish_degree_from_length_and_support_radians():
    doc = PartDocument(name="Ángulos", units=Units(angle="rad"), parameters=[
        Parameter(name="giro", value=math.pi / 2, kind="angle"),
        Parameter(name="altura", value="20 mm"),
    ])
    evaluator = QuantityEvaluator(doc)
    assert evaluator.angle("giro") == pytest.approx(90)
    assert evaluator.angle("90 deg") == 90
    assert evaluator.angle("1.5707963267948966 rad") == pytest.approx(90)
    assert evaluator.angle("pi * 0.5 rad") == pytest.approx(90)
    assert evaluator.resolved_angles() == {"giro": pytest.approx(90)}
    assert evaluator.resolved() == {"altura": 20}
    with pytest.raises(CadError) as error:
        evaluator.length("giro")
    assert error.value.code == "UNIT_MISMATCH"
    with pytest.raises(CadError) as error:
        evaluator.angle("pi/2 rad")
    assert error.value.code == "UNIT_MISMATCH"
    with pytest.raises(CadError) as error:
        evaluator.angle("altura")
    assert error.value.code == "UNIT_MISMATCH"


def test_revolve_cut_existing_body_and_reject_invalid_axis_or_crossed_profile(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Corte cilíndrico")
    cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 20, "width": 10, "height": 20,
                                            "origin": [-10, 0, -10]}},
        {"cmd": "sketch.new", "args": {"id": "seccion", "plane": "XY"}},
        {"cmd": "sketch.rectangle", "args": {"sketch": "seccion", "id": "radial", "center": [2, 5],
                                              "width": 4, "height": 10}},
        {"cmd": "feature.revolve", "args": {"id": "paso", "profile": "seccion", "axis": {"dir": [0, 1, 0]},
                                            "op": "cut", "target": "principal", "angle": "360 deg"}},
    ])
    assert cad.validate("p.iacad")["summary"]["volume_mm3"] == pytest.approx(4000 - math.pi * 4**2 * 10)
    before = (tmp_path / "p.iacad").read_bytes()
    for axis, code in [
        ({"origin": [0, 0, 0], "dir": [0, 0, 1]}, "AXIS_NOT_IN_SKETCH_PLANE"),
        ({"origin": [0, 0, 1], "dir": [0, 1, 0]}, "AXIS_NOT_IN_SKETCH_PLANE"),
        ({"origin": [2, 0, 0], "dir": [0, 1, 0]}, "PROFILE_CROSSES_AXIS"),
    ]:
        with pytest.raises(CadError) as error:
            cad.execute("p.iacad", [{"cmd": "feature.revolve", "args": {
                "id": "extra", "profile": "seccion", "axis": axis, "angle": "45 deg", "op": "cut", "target": "principal",
            }}])
        assert error.value.code == code
        assert (tmp_path / "p.iacad").read_bytes() == before


def test_zero_axis_out_of_range_angle_and_invalid_unit_reject_without_save(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "P")
    cad.execute("p.iacad", [
        {"cmd": "sketch.new", "args": {"id": "perfil", "plane": "XY"}},
        {"cmd": "sketch.rectangle", "args": {"sketch": "perfil", "id": "r", "center": [5, 5], "width": 5, "height": 10}},
    ])
    before = (tmp_path / "p.iacad").read_bytes()
    for angle, axis, code in [
        (0, {"dir": [0, 1, 0]}, "INVALID_ANGLE"),
        ("361 deg", {"dir": [0, 1, 0]}, "INVALID_ANGLE"),
        ("90 mm", {"dir": [0, 1, 0]}, "UNIT_MISMATCH"),
        ("90 deg", {"dir": [0, 0, 0]}, "INVALID_ARGUMENT"),
    ]:
        with pytest.raises(CadError) as error:
            cad.execute("p.iacad", [{"cmd": "feature.revolve", "args": {
                "id": "mal", "profile": "perfil", "axis": axis, "angle": angle, "body": "principal",
            }}])
        assert error.value.code == code
        assert (tmp_path / "p.iacad").read_bytes() == before


def test_circle_profile_crossing_axis_detected_between_seam_vertices(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("c.iacad", "Círculo cruzando el eje")
    cad.execute("c.iacad", [
        {"cmd": "sketch.new", "args": {"id": "p", "plane": "XY"}},
        {"cmd": "sketch.circle", "args": {"sketch": "p", "id": "c", "center": [2, 0], "radius": 5}},
    ])
    before = (tmp_path / "c.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("c.iacad", [{"cmd": "feature.revolve", "args": {
            "id": "s", "profile": "p", "axis": {"dir": [0, 1, 0]}, "body": "principal",
        }}])
    assert error.value.code == "PROFILE_CROSSES_AXIS"
    assert (tmp_path / "c.iacad").read_bytes() == before


def test_xz_sketch_can_revolve_around_global_z_axis(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("xz.iacad", "Casquillo vertical")
    result = cad.execute("xz.iacad", [
        {"cmd": "sketch.new", "args": {"id": "seccion", "plane": "XZ"}},
        {"cmd": "sketch.rectangle", "args": {"sketch": "seccion", "id": "pared", "center": [7.5, 10], "width": 5, "height": 20}},
        {"cmd": "feature.revolve", "args": {"id": "torneado", "profile": "seccion",
                                           "axis": {"dir": [0, 0, 1]}, "body": "principal"}},
    ])
    assert result["summary"]["volume_mm3"] == pytest.approx(math.pi * 75 * 20, abs=1e-5)
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [-10, -10, 0], "max": [10, 10, 20]}
