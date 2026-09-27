"""Undo/redo persistentes, checkpoints y adopción de ediciones de texto externas."""

import json

import pytest

from iacad.errors import CadError
from iacad.service import CADService
from iacad.storage import load


def test_undo_redo_checkpoint_and_branch(tmp_path):
    service = CADService(root=tmp_path)
    service.new("p.iacad", "Prueba de revisiones")
    service.execute("p.iacad", [
        {"cmd": "param.set", "args": {"name": "largo", "value": "10 mm"}},
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": "largo", "width": 5, "height": 5}},
    ])
    service.checkpoint("p.iacad", "original", expected_revision=1)
    service.execute("p.iacad", [{"cmd": "param.set", "args": {"name": "largo", "value": "20 mm"}}])

    # Nuevas instancias del servicio usan el historial persistido en disco.
    restarted = CADService(root=tmp_path)
    undone = restarted.navigate("p.iacad", "undo", expected_revision=2)
    assert undone["revision"] == 3
    assert undone["summary"]["bounds_mm"]["principal"]["max"][0] == 10
    assert restarted.navigate("p.iacad", "redo", expected_revision=3)["summary"]["bounds_mm"]["principal"]["max"][0] == 20
    assert restarted.navigate("p.iacad", "restore", expected_revision=4, name="original")["restored_revision"] == 1
    assert restarted.query("p.iacad", "params")["parameters_mm"]["largo"] == 10

    restarted.execute("p.iacad", [{"cmd": "param.set", "args": {"name": "largo", "value": "15 mm"}}], expected_revision=5)
    state = restarted.history("p.iacad")
    assert [entry["revision"] for entry in state["states"]] == [0, 1, 6]
    assert state["checkpoints"]["original"] == 1
    with pytest.raises(CadError) as error:
        restarted.navigate("p.iacad", "redo")
    assert error.value.code == "NO_HISTORY"
    assert load(tmp_path / "p.iacad").revision == 6
    assert list((tmp_path / ".iacad/revisions").rglob("*.iacad"))


def test_manual_edit_branches_history_instead_of_overwriting(tmp_path):
    service = CADService(root=tmp_path)
    service.new("p.iacad", "Inicial")
    service.execute("p.iacad", [{"cmd": "feature.box", "args": {"id": "a", "body": "principal", "length": 10, "width": 10, "height": 10}}])
    path = tmp_path / "p.iacad"
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["name"] = "Editado a mano"
    path.write_text(json.dumps(edited), encoding="utf-8")

    with pytest.raises(CadError) as error:
        service.navigate("p.iacad", "undo")
    assert error.value.code == "HISTORY_CHANGED"
    outcome = service.execute("p.iacad", [{"cmd": "param.set", "args": {"name": "lado", "value": "12 mm"}}])
    assert outcome["warnings"][0]["code"] == "HISTORY_RESET"
    assert [e["revision"] for e in service.history("p.iacad")["states"]] == [1, 2]
    service.navigate("p.iacad", "undo")
    assert load(path).name == "Editado a mano"
