"""Corte exacto por plano orientado que conserva un único lado."""

from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.service import CADService

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "placa_cortada.iacs"


def _split(**changes):
    return {"cmd": "feature.split", "args": {
        "id": "recorte", "target": "principal", "plane": {"origin": [20, 0, 0], "normal": [1, 0, 0]},
        **changes,
    }}


def test_oblique_split_example_step_cache_parameter_edit_and_undo(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/placa.iacad", "Placa recortada")
    made = cad.execute_script("parts/placa.iacad", EXAMPLE.read_text(encoding="utf-8"), expected_revision=0)
    assert made["summary"]["volume_mm3"] == pytest.approx(7500)
    assert made["summary"]["bounds_mm"]["principal"] == {
        "min": [10, 0, 0], "max": [40, 30, 10],
    }
    assert made["summary"]["bodies"] == 1 and made["checks"]["passed"] == 1
    assert made["cache"] == {"hits": 0, "misses": 2}
    assert CADService(root=tmp_path).validate("parts/placa.iacad")["cache"] == {"hits": 2, "misses": 0}
    assert all(item["ref"] is None for item in cad.query("parts/placa.iacad", "topology", kind="face")["items"])
    cad.export("parts/placa.iacad", "step", "out/placa.step")
    imported = import_step(tmp_path / "out/placa.step")
    assert imported.is_valid and imported.volume == pytest.approx(7500, abs=1e-5)

    moved = cad.execute("parts/placa.iacad", [{"cmd": "param.set", "args": {
        "name": "posicion", "value": "25 mm",
    }}])
    assert moved["summary"]["volume_mm3"] == pytest.approx(6000)
    assert moved["summary"]["bounds_mm"]["principal"] == {"min": [15, 0, 0], "max": [40, 30, 10]}
    assert moved["cache"] == {"hits": 1, "misses": 1}
    assert cad.navigate("parts/placa.iacad", "undo")["summary"]["volume_mm3"] == pytest.approx(7500)


@pytest.mark.parametrize(("direction", "keep"), [
    ([3, 0, 0], "negative"),
    ([-2, 0, 0], "positive"),
])
def test_split_keeps_opposite_side_with_normalized_or_reversed_normal(tmp_path, direction, keep):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Mitad negativa")
    made = cad.execute("p.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal",
                                        "length": 40, "width": 30, "height": 10}},
        _split(plane={"origin": [20, 0, 0], "normal": direction}, keep=keep),
    ])
    assert made["summary"]["volume_mm3"] == pytest.approx(6000)
    assert made["summary"]["bounds_mm"]["principal"] == {"min": [0, 0, 0], "max": [20, 30, 10]}


@pytest.mark.parametrize(("changes", "code"), [
    ({"plane": {"origin": [-10, 0, 0], "normal": [1, 0, 0]}}, "SPLIT_NO_EFFECT"),
    ({"plane": {"origin": [-10, 0, 0], "normal": [1, 0, 0]}, "keep": "negative"}, "SPLIT_EMPTY"),
    ({"plane": {"origin": [0, 0, 0], "normal": [1, 0, 0]}}, "SPLIT_NO_EFFECT"),
    ({"plane": {"origin": [20, 0, 0], "normal": [0, 0, 0]}}, "INVALID_ARGUMENT"),
    ({"plane": {"origin": ["5 deg", 0, 0], "normal": [1, 0, 0]}}, "UNIT_MISMATCH"),
    ({"keep": "both"}, "INVALID_ARGUMENT"),
    ({"target": "inexistente"}, "UNKNOWN_BODY"),
    ({"id": "base"}, "DUPLICATE_ID"),
])
def test_bad_split_rolls_back_and_dry_run_is_read_only(tmp_path, changes, code):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Split inválido")
    cad.execute("p.iacad", [{"cmd": "feature.box", "args": {"id": "base", "body": "principal",
                                                      "length": 40, "width": 30, "height": 10}}])
    before = (tmp_path / "p.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [_split(**changes)], expected_revision=1)
    assert error.value.code == code
    assert (tmp_path / "p.iacad").read_bytes() == before
    dry = cad.execute("p.iacad", [_split()], expected_revision=1, dry_run=True)
    assert dry["summary"]["volume_mm3"] == pytest.approx(6000)
    assert (tmp_path / "p.iacad").read_bytes() == before


def test_split_rejects_disconnected_remaining_half(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "U")
    cad.execute("p.iacad", [
        {"cmd": "sketch.new", "args": {"id": "perfil", "plane": "XY"}},
        {"cmd": "sketch.polyline", "args": {"sketch": "perfil", "id": "u", "points": [
            [0, 0], [30, 0], [30, 20], [25, 20], [25, 5], [5, 5], [5, 20], [0, 20],
        ]}},
        {"cmd": "feature.extrude", "args": {"id": "prisma", "profile": "perfil", "body": "principal",
                                        "extent": {"distance": 4}}},
    ])
    before = (tmp_path / "p.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [_split(plane={"origin": [0, 10, 0], "normal": [0, 1, 0]})])
    assert error.value.code == "SPLIT_FAILED"
    assert (tmp_path / "p.iacad").read_bytes() == before
