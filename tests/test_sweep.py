"""Barrido B-Rep por rutas 3D y rechazo de trayectorias engañosas."""

import math
from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.service import CADService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "tubo_acodado.iacs"


def _section(plane="XY", offset=0, outer=4, inner=None):
    commands = [
        {"cmd": "sketch.new", "args": {"id": "seccion", "plane": plane, "offset": offset}},
        {"cmd": "sketch.circle", "args": {"sketch": "seccion", "id": "exterior", "center": [0, 0], "radius": outer}},
    ]
    if inner is not None:
        commands.append({"cmd": "sketch.circle", "args": {"sketch": "seccion", "id": "hueco",
                                                 "center": [0, 0], "radius": inner}})
    return commands


def _sweep(points, **changes):
    return {"cmd": "feature.sweep", "args": {"id": "codo", "profile": "seccion",
             "path": {"points": points, "transition": "right"}, "body": "principal", **changes}}


def test_hollow_elbow_example_step_cache_edit_undo_and_render(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("tubo.iacad", "Tubo en L")
    first = cad.execute_script("tubo.iacad", EXAMPLE.read_text(encoding="utf-8"), expected_revision=0)
    assert first["summary"]["valid"] and first["summary"]["bodies"] == 1
    assert first["summary"]["volume_mm3"] == pytest.approx(360 * math.pi, abs=1e-5)
    assert first["summary"]["bounds_mm"]["principal"] == {"min": [-4, -4, 0], "max": [20, 4, 14]}
    assert first["cache"] == {"hits": 0, "misses": 1} and first["checks"]["passed"] == 1
    assert cad.validate("tubo.iacad")["cache"] == {"hits": 1, "misses": 0}
    cad.export("tubo.iacad", "step", "out/tubo.step")
    imported = import_step(tmp_path / "out/tubo.step")
    assert imported.is_valid and imported.volume == pytest.approx(360 * math.pi, rel=1e-7)
    preview = cad.render("tubo.iacad", "out/tubo.png", views="four", size=512)
    assert preview["views"] == "four" and (tmp_path / "out/tubo.png").stat().st_size > 0

    longer = cad.execute("tubo.iacad", [{"cmd": "param.set", "args": {"name": "salida", "value": "25 mm"}}])
    assert longer["cache"] == {"hits": 0, "misses": 1}
    assert longer["summary"]["volume_mm3"] == pytest.approx(420 * math.pi, abs=1e-5)
    assert longer["summary"]["bounds_mm"]["principal"]["max"][0] == 25
    restored = CADService(root=tmp_path).navigate("tubo.iacad", "undo", expected_revision=2)
    assert restored["cache"] == {"hits": 1, "misses": 0}
    assert restored["summary"]["volume_mm3"] == first["summary"]["volume_mm3"]


def test_round_transition_and_xz_negative_y_normal(tmp_path):
    cad = CADService(root=tmp_path)
    for mode in ("right", "round"):
        cad.new(f"{mode}.iacad", mode)
        made = cad.execute(f"{mode}.iacad", [*_section(inner=2), _sweep(
            [[0, 0, 0], [0, 0, 10], [20, 0, 10]], path={"points": [[0, 0, 0], [0, 0, 10], [20, 0, 10]],
                                                         "transition": mode})])
        assert made["summary"]["valid"]
        if mode == "right":
            assert made["summary"]["volume_mm3"] == pytest.approx(360 * math.pi, abs=1e-5)
        else:
            assert 0 < made["summary"]["volume_mm3"] < 360 * math.pi

    cad.new("xz.iacad", "Codo XZ")
    result = cad.execute("xz.iacad", [*_section(plane="XZ", offset=5, outer=2), _sweep(
        [[0, -5, 0], [0, -15, 0], [20, -15, 0]])])
    assert result["summary"]["volume_mm3"] == pytest.approx(120 * math.pi, abs=1e-5)
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [-2, -17, -2], "max": [20, -5, 2]}

    cad.new("reverse.iacad", "Tramo en -Z")
    reverse = cad.execute("reverse.iacad", [*_section(outer=2), _sweep([[0, 0, 0], [0, 0, -10]])])
    assert reverse["summary"]["volume_mm3"] == pytest.approx(40 * math.pi, abs=1e-5)
    assert reverse["summary"]["bounds_mm"]["principal"] == {"min": [-2, -2, -10], "max": [2, 2, 0]}


def test_sweep_boolean_cut_and_join(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("cut.iacad", "Corte por trayectoria")
    cut = cad.execute("cut.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 20, "width": 20,
                                        "height": 20, "origin": [-10, -10, 0]}},
        *_section(outer=3),
        _sweep([[0, 0, 0], [0, 0, 20]], op="cut", target="principal", body=None),
    ])
    assert cut["summary"]["bodies"] == 1
    assert cut["summary"]["volume_mm3"] == pytest.approx(8000 - 180 * math.pi, abs=1e-5)
    assert all(face["ref"] is None for face in cad.query("cut.iacad", "topology", kind="face")["items"])

    cad.new("join.iacad", "Añadido por trayectoria")
    joined = cad.execute("join.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 20, "width": 20,
                                        "height": 5, "origin": [-10, -10, 0]}},
        *_section(offset=5, outer=2),
        _sweep([[0, 0, 5], [0, 0, 15]], op="join", target="principal", body=None),
    ])
    assert joined["summary"]["valid"] and joined["summary"]["volume_mm3"] == pytest.approx(2000 + 40 * math.pi)


def test_bad_path_or_profile_never_changes_document(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Rutas")
    cad.execute("p.iacad", _section(outer=2))
    before = (tmp_path / "p.iacad").read_bytes()
    valid = [[0, 0, 0], [0, 0, 10], [20, 0, 10]]
    cases = [
        ([[0, 0, 3], [0, 0, 13]], "PATH_NOT_ON_SKETCH"),
        ([[0, 0, 0], [10, 0, 0]], "PATH_NOT_NORMAL"),
        ([[0, 0, 0], [0, 0, 0]], "PATH_INVALID"),
        ([[0, 0, 0], [0, 0, 10], [0, 0, 10]], "PATH_INVALID"),
        ([[0, 0, 0], [0, 0, "10 deg"]], "UNIT_MISMATCH"),
    ]
    for points, code in cases:
        with pytest.raises(CadError) as error:
            cad.execute("p.iacad", [_sweep(points)], expected_revision=1)
        assert error.value.code == code
        assert (tmp_path / "p.iacad").read_bytes() == before
    for changes in [
        {"path": {"points": [[0, 0, 0]], "transition": "right"}},
        {"path": {"points": valid, "transition": "transformed"}},
        {"profile": "otro"},
    ]:
        with pytest.raises(CadError) as error:
            cad.execute("p.iacad", [_sweep(valid, **changes)], expected_revision=1)
        assert error.value.code == ("UNKNOWN_SKETCH" if changes.get("profile") else "INVALID_ARGUMENT")
        assert (tmp_path / "p.iacad").read_bytes() == before
    dry = cad.execute("p.iacad", [_sweep(valid)], dry_run=True, expected_revision=1)
    assert dry["summary"]["volume_mm3"] == pytest.approx(120 * math.pi, abs=1e-5)
    assert (tmp_path / "p.iacad").read_bytes() == before
