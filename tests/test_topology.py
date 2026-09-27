"""Referencias geométricas semánticas, cardinalidad explícita y operaciones de acabado."""

from pathlib import Path

import pytest

from iacad.errors import CadError
from iacad.scripts import parse_script
from iacad.service import CADService


def _box(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("p.iacad", "Prisma")
    cad.execute("p.iacad", [
        {"cmd": "param.set", "args": {"name": "largo", "value": "40 mm"}},
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": "largo", "width": 30, "height": 10}},
    ])
    return cad


def test_query_stable_box_faces_edges_across_parameter_changes_and_cache(tmp_path):
    cad = _box(tmp_path)
    result = cad.query("p.iacad", "topology", body="principal", limit=100)
    assert result["total"] == 18
    refs = {item["ref"] for item in result["items"]}
    assert "@base/face:xmin" in refs
    assert "@base/face:zmax" in refs
    assert "@base/edge:xmax&ymax" in refs
    assert len([ref for ref in refs if ref and "/face:" in ref]) == 6
    assert len([ref for ref in refs if ref and "/edge:" in ref]) == 12
    paged = cad.query("p.iacad", "topology", body="principal", kind="edge", limit=5)
    assert paged["total"] == 12 and len(paged["items"]) == 5 and paged["next_cursor"] == 5
    last = cad.query("p.iacad", "topology", body="principal", kind="edge", limit=10, cursor=5)
    assert len(last["items"]) == 7 and last["next_cursor"] is None

    changed = cad.execute("p.iacad", [{"cmd": "param.set", "args": {"name": "largo", "value": "50 mm"}}])
    assert changed["summary"]["bounds_mm"]["principal"]["max"][0] == 50
    reopened = CADService(root=tmp_path)
    renamed = reopened.query("p.iacad", "topology", body="principal")
    assert {item["ref"] for item in renamed["items"]} == refs
    assert renamed["cache"] == {"hits": 1, "misses": 0}


def test_fillet_named_edge_and_chamfer_semantic_selector(tmp_path):
    cad = _box(tmp_path)
    rounded = cad.execute("p.iacad", [{
        "cmd": "feature.fillet", "args": {
            "id": "redondeo", "target": "principal", "radius": "2 mm",
            "edges": {"refs": ["@base/edge:xmax&ymax"], "expect": "one"},
        },
    }])
    assert rounded["summary"]["valid"] and 0 < rounded["summary"]["volume_mm3"] < 12_000
    assert "@base/edge:xmax&ymax" not in {item["ref"] for item in cad.query("p.iacad", "topology", kind="edge")["items"]}
    before = (tmp_path / "p.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [{
            "cmd": "feature.chamfer", "args": {"id": "f", "target": "principal", "distance": 1,
                                                 "edges": {"refs": ["@base/edge:xmax&ymax"], "expect": 1}},
        }])
    assert error.value.code == "REF_LOST" and (tmp_path / "p.iacad").read_bytes() == before

    cad.new("c.iacad", "Chaflán")
    chamfered = cad.execute("c.iacad", parse_script(
        "feature.box id=base body=principal length=40mm width=30mm height=10mm\n"
        "feature.chamfer id=esquina target=principal edges='?principal/edges[|Z and >X and >Y]' expect=one distance=1mm"
    ))
    assert chamfered["summary"]["valid"]
    assert chamfered["summary"]["volume_mm3"] == pytest.approx(11995, abs=1e-5)


def test_ambiguous_or_invalid_selection_rolls_back(tmp_path):
    cad = _box(tmp_path)
    before = (tmp_path / "p.iacad").read_bytes()
    for edges, code in [
        ({"query": {"scope": "principal", "kind": "edge", "where": "|Z and >X"}, "expect": "one"}, "SELECTION_COUNT"),
        ({"query": {"scope": "principal", "kind": "edge", "where": "|Z or >X"}, "expect": 1}, "INVALID_SELECTOR"),
        ({"refs": ["@otra/edge:xmax&ymax"], "expect": "one"}, "REF_LOST"),
    ]:
        with pytest.raises(CadError) as error:
            cad.execute("p.iacad", [{"cmd": "feature.fillet", "args": {"id": "f", "target": "principal", "edges": edges, "radius": 1}}])
        assert error.value.code == code
        assert (tmp_path / "p.iacad").read_bytes() == before


def test_box_edge_remains_after_nonintersecting_hole_then_fillet(tmp_path):
    cad = _box(tmp_path)
    cad.execute("p.iacad", [
        {"cmd": "feature.cylinder", "args": {"id": "broca", "body": "herramienta", "radius": 4, "height": 10, "origin": [20, 15, 0]}},
        {"cmd": "feature.boolean", "args": {"id": "taladro", "op": "cut", "target": "principal", "tools": ["herramienta"]}},
        {"cmd": "feature.fillet", "args": {"id": "radio", "target": "principal", "radius": 2,
                                            "edges": {"refs": ["@base/edge:xmax&ymax"], "expect": 1}}},
    ])
    assert cad.validate("p.iacad")["summary"]["valid"]


def test_documented_fillet_survives_parameter_change_and_undo(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("caja.iacad", "Caja con arista redondeada")
    script = Path(__file__).resolve().parents[1] / "examples" / "caja_redondeada.iacs"
    original = cad.execute_script("caja.iacad", script.read_text(encoding="utf-8"))
    assert original["checks"]["passed"] == 1
    assert original["cache"] == {"hits": 0, "misses": 2}
    after = cad.execute("caja.iacad", [{"cmd": "param.set", "args": {"name": "largo", "value": "50 mm"}}])
    assert after["cache"] == {"hits": 0, "misses": 2}
    assert after["summary"]["volume_mm3"] == pytest.approx(original["summary"]["volume_mm3"] + 3000, abs=1e-4)
    undo = CADService(root=tmp_path).navigate("caja.iacad", "undo", expected_revision=2)
    assert undo["cache"] == {"hits": 2, "misses": 0}
    assert undo["summary"]["volume_mm3"] == original["summary"]["volume_mm3"]


def test_range_cardinality_and_invalid_kind_are_checked(tmp_path):
    cad = _box(tmp_path)
    result = cad.execute("p.iacad", [{"cmd": "feature.fillet", "args": {
        "id": "cuatro_esquinas", "target": "principal", "radius": 1,
        "edges": {"query": {"scope": "principal", "kind": "edge", "where": "%LINE and |Z"}, "expect": "2..4"},
    }}])
    assert result["summary"]["valid"]
    before = (tmp_path / "p.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        cad.execute("p.iacad", [{"cmd": "feature.chamfer", "args": {
            "id": "erroneo", "target": "principal", "distance": 1,
            "edges": {"query": {"scope": "principal", "kind": "edge", "where": "%PLANE"}, "expect": 1},
        }}])
    assert error.value.code == "INVALID_SELECTOR"
    assert (tmp_path / "p.iacad").read_bytes() == before


def test_topology_query_rejects_invalid_pagination_or_project(tmp_path):
    cad = _box(tmp_path)
    with pytest.raises(CadError) as error:
        cad.query("p.iacad", "topology", cursor=-1)
    assert error.value.code == "INVALID_ARGUMENT"
    cad.new("proyecto.iacad", "P", kind="project")
    with pytest.raises(CadError) as error:
        cad.query("proyecto.iacad", "topology")
    assert error.value.code == "WRONG_DOCUMENT_KIND"
