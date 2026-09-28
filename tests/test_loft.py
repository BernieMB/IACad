"""Loft entre croquis paralelos, offsets, booleana y validación transaccional."""

import math
from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.service import CADService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "cono_truncado.iacs"


def _circle_section(name: str, offset: int | str, radius: int | str) -> list[dict]:
    return [
        {"cmd": "sketch.new", "args": {"id": name, "plane": "XY", "offset": offset}},
        {"cmd": "sketch.circle", "args": {"sketch": name, "id": "disco", "center": [0, 0], "radius": radius}},
    ]


def test_frustum_example_step_cache_edit_undo_and_render(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/cono.iacad", "Cono truncado")
    first = cad.execute_script("parts/cono.iacad", EXAMPLE.read_text(encoding="utf-8"), expected_revision=0)
    expected = math.pi * 20 * (10**2 + 10 * 5 + 5**2) / 3
    assert first["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    assert first["checks"]["passed"] == 1
    assert first["cache"] == {"hits": 0, "misses": 1}
    bounds = first["summary"]["bounds_mm"]["principal"]
    assert bounds["min"] == pytest.approx([-10, -10, 0], abs=1e-5)
    assert bounds["max"] == pytest.approx([10, 10, 20], abs=1e-5)
    assert CADService(root=tmp_path).validate("parts/cono.iacad")["cache"] == {"hits": 1, "misses": 0}
    cad.export("parts/cono.iacad", "step", "out/cono.step")
    imported = import_step(tmp_path / "out/cono.step")
    assert imported.is_valid and imported.volume == pytest.approx(expected, rel=1e-7)
    rendered = cad.render("parts/cono.iacad", "out/cono.png", views="four", size=512)
    assert rendered["views"] == "four" and (tmp_path / "out/cono.png").stat().st_size > 0

    changed = cad.execute("parts/cono.iacad", [{"cmd": "param.set", "args": {"name": "radio_superior", "value": "6 mm"}}])
    assert changed["cache"] == {"hits": 0, "misses": 1}
    assert changed["summary"]["volume_mm3"] == pytest.approx(math.pi * 20 * (100 + 60 + 36) / 3, abs=1e-5)
    moved = cad.execute("parts/cono.iacad", [{"cmd": "param.set", "args": {"name": "altura", "value": "25 mm"}}])
    assert moved["summary"]["bounds_mm"]["principal"]["max"][2] == 25
    assert moved["cache"] == {"hits": 0, "misses": 1}
    undo = CADService(root=tmp_path).navigate("parts/cono.iacad", "undo", expected_revision=3)
    assert undo["cache"] == {"hits": 1, "misses": 0}
    assert undo["summary"]["volume_mm3"] == changed["summary"]["volume_mm3"]


def test_sketch_offset_extrusion_and_revolution_preserve_plane_normal(tmp_path):
    cad = CADService(root=tmp_path)
    for name, plane, offset, expected in [
        ("xy", "XY", 5, {"min": [-2, -2, 5], "max": [2, 2, 11]}),
        ("xz", "XZ", 5, {"min": [-2, -11, -2], "max": [2, -5, 2]}),
        ("yz", "YZ", 5, {"min": [5, -2, -2], "max": [11, 2, 2]}),
    ]:
        cad.new(f"{name}.iacad", name)
        result = cad.execute(f"{name}.iacad", [
            {"cmd": "sketch.new", "args": {"id": "perfil", "plane": plane, "offset": offset}},
            {"cmd": "sketch.circle", "args": {"sketch": "perfil", "id": "disco", "center": [0, 0], "radius": 2}},
            {"cmd": "feature.extrude", "args": {"id": "cilindro", "profile": "perfil", "extent": {"distance": 6}, "body": "principal"}},
        ])
        assert result["summary"]["bounds_mm"]["principal"] == expected

    cad.new("torno.iacad", "Torno desplazado")
    cad.execute("torno.iacad", [
        {"cmd": "sketch.new", "args": {"id": "perfil", "plane": "XZ", "offset": "5 mm"}},
        {"cmd": "sketch.rectangle", "args": {"sketch": "perfil", "id": "r", "center": [5, 5], "width": 10, "height": 10}},
    ])
    before = (tmp_path / "torno.iacad").read_bytes()
    axis = {"origin": [0, 0, 0], "dir": [0, 0, 1]}
    with pytest.raises(CadError) as error:
        cad.execute("torno.iacad", [{"cmd": "feature.revolve", "args": {
            "id": "torneado", "profile": "perfil", "axis": axis, "body": "principal",
        }}])
    assert error.value.code == "AXIS_NOT_IN_SKETCH_PLANE"
    assert (tmp_path / "torno.iacad").read_bytes() == before
    axis["origin"] = [0, -5, 0]
    made = cad.execute("torno.iacad", [{"cmd": "feature.revolve", "args": {
        "id": "torneado", "profile": "perfil", "axis": axis, "body": "principal",
    }}])
    assert made["summary"]["volume_mm3"] == pytest.approx(math.pi * 10**2 * 10, abs=1e-5)
    assert made["summary"]["bounds_mm"]["principal"]["min"] == [-10, -15, 0]


def test_loft_between_hollow_sections_and_boolean_cut(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("hueco.iacad", "Cono hueco")
    sections = [
        *_circle_section("abajo", 0, 10),
        {"cmd": "sketch.circle", "args": {"sketch": "abajo", "id": "hueco", "center": [0, 0], "radius": 3}},
        *_circle_section("arriba", 20, 6),
        {"cmd": "sketch.circle", "args": {"sketch": "arriba", "id": "hueco", "center": [0, 0], "radius": 2}},
    ]
    result = cad.execute("hueco.iacad", [*sections, {"cmd": "feature.loft", "args": {
        "id": "transicion", "sections": ["abajo", "arriba"], "body": "principal",
    }}])
    expected = math.pi * 20 * ((100 + 60 + 36) - (9 + 6 + 4)) / 3
    assert result["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)

    cad.new("corte.iacad", "Corte con loft")
    cut = cad.execute("corte.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 20, "width": 20,
                                        "height": 20, "origin": [-10, -10, 0]}},
        *_circle_section("inferior", 0, 5),
        *_circle_section("superior", 20, 8),
        {"cmd": "feature.loft", "args": {"id": "paso", "sections": ["inferior", "superior"],
                                           "op": "cut", "target": "principal"}},
    ])
    assert cut["summary"]["bodies"] == 1
    assert cut["summary"]["volume_mm3"] == pytest.approx(8000 - math.pi * 20 * (25 + 40 + 64) / 3, abs=1e-5)


def test_xz_loft_follows_negative_y_normal(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("xz.iacad", "Secciones XZ")
    result = cad.execute("xz.iacad", [
        {"cmd": "sketch.new", "args": {"id": "primera", "plane": "XZ"}},
        {"cmd": "sketch.circle", "args": {"sketch": "primera", "id": "disco", "center": [0, 0], "radius": 3}},
        {"cmd": "sketch.new", "args": {"id": "segunda", "plane": "XZ", "offset": 12}},
        {"cmd": "sketch.circle", "args": {"sketch": "segunda", "id": "disco", "center": [0, 0], "radius": 3}},
        {"cmd": "feature.loft", "args": {"id": "cilindro", "sections": ["segunda", "primera"], "body": "principal"}},
    ])
    assert result["summary"]["valid"]
    assert result["summary"]["volume_mm3"] == pytest.approx(math.pi * 3**2 * 12, abs=1e-5)
    assert result["summary"]["bounds_mm"]["principal"]["min"] == pytest.approx([-3, -12, -3], abs=1e-5)


def test_loft_join_and_intersect_existing_box(tmp_path):
    cad = CADService(root=tmp_path)
    for operation in ("join", "intersect"):
        cad.new(f"{operation}.iacad", operation)
        result = cad.execute(f"{operation}.iacad", [
            {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 20, "width": 20,
                                            "height": 10, "origin": [-10, -10, 0]}},
            *_circle_section("inferior", 0, 5),
            *_circle_section("superior", 20, 8),
            {"cmd": "feature.loft", "args": {"id": "perfilado", "sections": ["inferior", "superior"],
                                               "op": operation, "target": "principal"}},
        ])
        assert result["summary"]["bodies"] == 1 and result["summary"]["valid"]
        if operation == "join":
            assert result["summary"]["bounds_mm"]["principal"]["max"][2] == pytest.approx(20, abs=1e-5)
            assert result["summary"]["volume_mm3"] > 4000
        else:
            expected = math.pi * 10 * (5**2 + 5 * 6.5 + 6.5**2) / 3
            assert result["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-4)


def test_loft_invalid_section_sets_are_atomic(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Perfiles")
    cad.execute("p.iacad", [
        *_circle_section("a", 0, 10),
        *_circle_section("b", 10, 8),
        *_circle_section("c", 20, 5),
        {"cmd": "sketch.new", "args": {"id": "otro_plano", "plane": "XZ", "offset": 30}},
        {"cmd": "sketch.circle", "args": {"sketch": "otro_plano", "id": "c", "center": [0, 0], "radius": 5}},
        {"cmd": "sketch.new", "args": {"id": "mismo_offset", "plane": "XY", "offset": 10}},
        {"cmd": "sketch.circle", "args": {"sketch": "mismo_offset", "id": "c", "center": [0, 0], "radius": 5}},
        {"cmd": "sketch.new", "args": {"id": "hueco", "plane": "XY", "offset": 30}},
        {"cmd": "sketch.circle", "args": {"sketch": "hueco", "id": "c", "center": [0, 0], "radius": 10}},
        {"cmd": "sketch.circle", "args": {"sketch": "hueco", "id": "i", "center": [0, 0], "radius": 2}},
    ])
    before = (tmp_path / "p.iacad").read_bytes()
    for names, code in [
        (["a", "x"], "UNKNOWN_SKETCH"),
        (["a", "a"], "INVALID_ARGUMENT"),
        (["a", "otro_plano"], "PROFILE_PLANES_MISMATCH"),
        (["b", "mismo_offset"], "SECTIONS_NOT_ORDERED"),
        (["a", "c", "b"], "SECTIONS_NOT_ORDERED"),
        (["a", "hueco"], "PROFILE_HOLES_MISMATCH"),
    ]:
        with pytest.raises(CadError) as error:
            cad.execute("p.iacad", [{"cmd": "feature.loft", "args": {
                "id": "malo", "sections": names, "body": "principal",
            }}], expected_revision=1)
        assert error.value.code == code
        assert (tmp_path / "p.iacad").read_bytes() == before
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [{"cmd": "sketch.new", "args": {
            "id": "error", "plane": "YZ", "offset": "5 deg",
        }}])
    assert error.value.code == "UNIT_MISMATCH"
    assert (tmp_path / "p.iacad").read_bytes() == before


def test_three_sections_ruled_and_smooth_and_empty_profile(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("tres.iacad", "Tres secciones")
    sections = [*_circle_section("a", 0, 10), *_circle_section("b", 10, 8), *_circle_section("c", 20, 5)]
    ruled = cad.execute("tres.iacad", [*sections, {"cmd": "feature.loft", "args": {
        "id": "transicion", "sections": ["a", "b", "c"], "ruled": True, "body": "principal",
    }}])
    expected = math.pi * 10 * ((100 + 80 + 64) + (64 + 40 + 25)) / 3
    assert ruled["summary"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    cad.new("suave.iacad", "Tres secciones suaves")
    smooth = cad.execute("suave.iacad", [*sections, {"cmd": "feature.loft", "args": {
        "id": "transicion", "sections": ["a", "b", "c"], "ruled": False, "body": "principal",
    }}])
    assert smooth["summary"]["valid"] and smooth["summary"]["volume_mm3"] > 0

    cad.new("vacio.iacad", "Sección vacía")
    cad.execute("vacio.iacad", [*_circle_section("a", 0, 10), {"cmd": "sketch.new", "args": {
        "id": "vacia", "plane": "XY", "offset": 10,
    }}])
    before = (tmp_path / "vacio.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("vacio.iacad", [{"cmd": "feature.loft", "args": {
            "id": "malo", "sections": ["a", "vacia"], "body": "principal",
        }}])
    assert error.value.code == "PROFILE_INVALID"
    assert (tmp_path / "vacio.iacad").read_bytes() == before
