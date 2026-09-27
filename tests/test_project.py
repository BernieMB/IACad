"""Manifiesto de proyecto: brief trazable, identidad de piezas y transacciones seguras."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from iacad.cli import app
from iacad.errors import CadError
from iacad.model import DOCUMENT_ADAPTER, ProjectDocument
from iacad.service import CADService
from iacad.storage import encode, load


def test_project_links_parts_and_traces_requirement(tmp_path):
    service = CADService(root=tmp_path)
    service.new("proyecto.iacad", "Mi proyecto", kind="project")
    part = service.new("parts/placa.iacad", "Placa")
    service.execute("parts/placa.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 40, "width": 30, "height": 6}},
        {"cmd": "check.add", "args": {"id": "cotas", "type": "bbox_max", "target": "principal", "value": [40, 30, 6]}},
    ])
    project_commands = [
        {"cmd": "project.brief", "args": {"summary": "Placa de 40×30×6 con control de cotas", "assumptions": ["mm"]}},
        {"cmd": "project.link", "args": {"path": "parts/placa.iacad", "uid": part["uid"], "kind": "part"}},
        {"cmd": "project.requirement", "args": {"id": "REQ-1", "text": "Caber en 40×30×6 mm", "verified_by": ["parts/placa.iacad#check:cotas"]}},
    ]
    dry_run = service.execute("proyecto.iacad", project_commands, dry_run=True, expected_revision=0)
    assert dry_run["summary"] == {"documents": 1, "requirements": 1, "references_valid": True}
    assert load(tmp_path / "proyecto.iacad").revision == 0
    result = service.execute("proyecto.iacad", project_commands, expected_revision=0)
    assert result["revision"] == 1
    assert service.validate("proyecto.iacad")["ok"]
    assert service.query("proyecto.iacad", "brief")["brief"]["requirements"][0]["id"] == "REQ-1"
    saved = load(tmp_path / "proyecto.iacad")
    assert isinstance(saved, ProjectDocument)
    assert saved.documents[0].uid == part["uid"]
    assert DOCUMENT_ADAPTER.validate_json(encode(saved)) == saved
    assert service.navigate("proyecto.iacad", "undo", expected_revision=1)["summary"]["documents"] == 0
    assert service.navigate("proyecto.iacad", "redo", expected_revision=2)["summary"]["requirements"] == 1
    service.execute("proyecto.iacad", [{"cmd": "project.requirement", "args": {"id": "REQ-1", "text": "Caber en 40×30×6 mm (actualizado)"}}])
    assert service.query("proyecto.iacad", "brief")["brief"]["requirements"][0]["verified_by"] == ["parts/placa.iacad#check:cotas"]


def test_project_rejects_wrong_kind_broken_links_and_escape(tmp_path):
    service = CADService(root=tmp_path)
    service.new("design/proyecto.iacad", "Diseño", kind="project")
    part = service.new("design/parts/p.iacad", "P")
    project_file = tmp_path / "design/proyecto.iacad"
    original = project_file.read_bytes()
    for ref in [
        {"path": "parts/p.iacad", "uid": "0" * 26},
        {"path": "../fuera.iacad", "uid": part["uid"]},
        {"path": "parts/no_existe.iacad", "uid": part["uid"]},
    ]:
        with pytest.raises(CadError) as error:
            service.execute("design/proyecto.iacad", [{"cmd": "project.link", "args": ref}])
        assert error.value.code in ("DOC_REF_MISMATCH", "INVALID_REFERENCE", "BROKEN_DOC_REF")
        assert project_file.read_bytes() == original
    with pytest.raises(CadError) as error:
        service.execute("design/proyecto.iacad", [{"cmd": "feature.box", "args": {"id": "b", "body": "x", "length": 1, "width": 1, "height": 1}}])
    assert error.value.code == "WRONG_DOCUMENT_KIND"
    with pytest.raises(CadError) as error:
        service.execute("design/parts/p.iacad", [{"cmd": "project.brief", "args": {"summary": "No"}}])
    assert error.value.code == "WRONG_DOCUMENT_KIND"
    with pytest.raises(CadError) as error:
        service.export("design/proyecto.iacad", "step", "out/proyecto.step")
    assert error.value.code == "WRONG_DOCUMENT_KIND"


def test_project_detects_later_uid_change_or_missing_check(tmp_path):
    service = CADService(root=tmp_path)
    service.new("proyecto.iacad", "P", kind="project")
    part = service.new("parts/elemento.iacad", "E")
    service.execute("parts/elemento.iacad", [
        {"cmd": "feature.box", "args": {"id": "bloque", "body": "principal", "length": 2, "width": 2, "height": 2}},
    ])
    service.execute("proyecto.iacad", [{"cmd": "project.link", "args": {"path": "parts/elemento.iacad", "uid": part["uid"]}}])
    before = (tmp_path / "proyecto.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        service.execute("proyecto.iacad", [{"cmd": "project.requirement", "args": {"id": "REQ-1", "text": "Un check", "verified_by": ["parts/elemento.iacad#check:inexistente"]}}])
    assert error.value.code == "BROKEN_VERIFICATION"
    assert (tmp_path / "proyecto.iacad").read_bytes() == before
    edited = json.loads((tmp_path / "parts/elemento.iacad").read_text(encoding="utf-8"))
    edited["uid"] = "0" * 26
    (tmp_path / "parts/elemento.iacad").write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(CadError) as error:
        service.validate("proyecto.iacad")
    assert error.value.code == "DOC_REF_MISMATCH"
    service.execute("proyecto.iacad", [{"cmd": "project.link", "args": {"path": "parts/elemento.iacad", "uid": "0" * 26}}])
    assert service.validate("proyecto.iacad")["summary"]["references_valid"]
    service.execute("proyecto.iacad", [{"cmd": "project.unlink", "args": {"path": "parts/elemento.iacad"}}])
    assert service.validate("proyecto.iacad")["summary"]["documents"] == 0


def test_cli_creates_project_with_json_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("IACAD_WORKSPACE", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["new", "proyecto.iacad", "--name", "Demo", "--kind", "project"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["kind"] == "project"
    schema = runner.invoke(app, ["schema"])
    assert schema.exit_code == 0, schema.output
    assert "ProjectDocument" in schema.stdout


def test_documented_project_script_runs_without_part_links(tmp_path):
    script = Path(__file__).resolve().parents[1] / "examples" / "proyecto.iacs"
    service = CADService(root=tmp_path)
    service.new("proyecto.iacad", "Placa", kind="project")
    result = service.execute_script("proyecto.iacad", script.read_text(encoding="utf-8"))
    assert result["summary"]["requirements"] == 2
    assert service.query("proyecto.iacad", "brief")["brief"]["assumptions"] == ["Cotas en mm"]
