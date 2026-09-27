import json
import math
from pathlib import Path

import pytest
from build123d import import_step

from iacad.errors import CadError
from iacad.model import PartDocument
from iacad.scripts import parse_script
from iacad.service import CADService
from iacad.storage import encode, load

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "placa.iacs"


@pytest.fixture
def project(tmp_path):
    service = CADService(root=tmp_path)
    service.new("parts/placa.iacad", "Placa de prueba")
    return service


def test_script_export_roundtrip_and_audit(project, tmp_path):
    result = project.execute_script("parts/placa.iacad", EXAMPLE.read_text(encoding="utf-8"), expected_revision=0)
    assert result["revision"] == 1
    assert result["summary"]["bodies"] == 1
    assert result["summary"]["bounds_mm"]["principal"] == {"min": [0, 0, 0], "max": [40, 30, 6]}
    expected_volume = 40 * 30 * 6 - math.pi * 4**2 * 6
    assert result["summary"]["volume_mm3"] == pytest.approx(expected_volume, abs=1e-5)
    assert result["checks"]["passed"] == 3

    saved = load(tmp_path / "parts/placa.iacad")
    assert saved.kind == "part"
    assert [f.id for f in saved.features] == ["base", "broca", "orificio"]
    assert [b.id for b in saved.bodies] == ["principal"]
    assert project.validate("parts/placa.iacad")["summary"] == result["summary"]

    exported = project.export("parts/placa.iacad", "step", "out/placa.step")
    assert exported["file"] == "out/placa.step"
    imported = import_step(tmp_path / "out/placa.step")
    assert imported.is_valid
    assert imported.volume == pytest.approx(expected_volume, rel=1e-7)
    project.export("parts/placa.iacad", "stl", "out/placa.stl")
    assert (tmp_path / "out/placa.stl").stat().st_size > 84

    journal = list((tmp_path / "journal").glob("*.jsonl"))
    events = [json.loads(line) for line in journal[0].read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in events] == ["doc_new", "command", "export", "export"]
    assert events[1]["status"] == "ok"
    assert events[2]["rev"] == 1


def test_dry_run_and_failed_geometry_never_modify_document(project, tmp_path):
    path = tmp_path / "parts/placa.iacad"
    before = path.read_bytes()
    box = [{"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": "10 mm", "width": "20 mm", "height": "5 mm"}}]
    result = project.execute("parts/placa.iacad", box, dry_run=True)
    assert result["dry_run"] and result["revision"] == 0
    assert path.read_bytes() == before

    bad = [{"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": "-10 mm", "width": "20 mm", "height": "5 mm"}}]
    with pytest.raises(CadError, match="mayor que cero") as error:
        project.execute("parts/placa.iacad", bad)
    assert error.value.code == "INVALID_DIMENSION"
    assert path.read_bytes() == before
    events = [json.loads(line) for line in next((tmp_path / "journal").glob("*.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert events[-1]["status"] == "rejected"
    assert len(events) == 2  # doc_new + rechazo; dry_run sin journal


def test_revision_conflict_and_path_traversal(project, tmp_path):
    commands = parse_script("feature.box id=base body=principal length=10mm width=20mm height=5mm")
    project.execute("parts/placa.iacad", commands, expected_revision=0)
    before = (tmp_path / "parts/placa.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        project.execute("parts/placa.iacad", commands, expected_revision=0)
    assert error.value.code == "REVISION_CONFLICT"
    assert (tmp_path / "parts/placa.iacad").read_bytes() == before
    with pytest.raises(CadError) as error:
        project.new("../escape.iacad", "No")
    assert error.value.code == "PATH_OUTSIDE_WORKSPACE"
    with pytest.raises(CadError) as error:
        project.export("parts/placa.iacad", "step", "../escape.step")
    assert error.value.code == "PATH_OUTSIDE_WORKSPACE"


def test_units_expressions_and_cycle_detection(project):
    commands = parse_script("param.set ancho='2 in'\nfeature.box id=base body=principal length='ancho + 5 mm' width=10 height=5")
    result = project.execute("parts/placa.iacad", commands)
    assert result["summary"]["bounds_mm"]["principal"]["max"] == [55.8, 10, 5]
    assert project.query("parts/placa.iacad", "params")["parameters_mm"] == {"ancho": 50.8}
    with pytest.raises(CadError) as error:
        project.execute("parts/placa.iacad", parse_script("param.set a=b b=a"))
    assert error.value.code == "PARAM_CYCLE"


def test_unsafe_expression_and_unknown_command_are_rejected(project):
    with pytest.raises(CadError) as error:
        project.execute("parts/placa.iacad", parse_script("param.set x=__import__('os').system('whoami')"))
    assert error.value.code in ("UNSAFE_EXPRESSION", "INVALID_EXPRESSION")
    with pytest.raises(CadError) as error:
        project.execute("parts/placa.iacad", [{"cmd": "feature.unimplemented", "args": {"id": "f", "radius": 1}}])
    assert error.value.code == "UNKNOWN_COMMAND"


def test_json_schema_and_roundtrip_are_stable():
    doc = PartDocument(name="pieza")
    assert PartDocument.model_json_schema()["properties"]["kind"]["const"] == "part"
    assert encode(PartDocument.model_validate_json(encode(doc))) == encode(doc)


def test_script_reports_line_number():
    with pytest.raises(CadError) as error:
        parse_script("param.set a=1mm\nfeature.box argumento_sin_igual")
    assert error.value.code == "SCRIPT_SYNTAX"
    assert error.value.path == "line:2"


def test_failing_design_check_still_saves_but_blocks_validation_and_export(project, tmp_path):
    result = project.execute("parts/placa.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 10, "width": 10, "height": 10}},
        {"cmd": "check.add", "args": {"id": "minimo", "type": "volume_min", "target": "principal", "value": "2 cm^3"}},
    ])
    assert result["revision"] == 1 and result["checks"]["failed"] == 1
    assert not project.validate("parts/placa.iacad")["ok"]
    with pytest.raises(CadError) as error:
        project.export("parts/placa.iacad", "step", "out/invalid.step")
    assert error.value.code == "CHECK_FAILED"
    assert not (tmp_path / "out/invalid.step").exists()
