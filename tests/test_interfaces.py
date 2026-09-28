"""Pruebas de las interfaces que consume el agente (no solo del motor interno)."""

import json
import math
import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from typer.testing import CliRunner

from iacad.cli import app


def test_cli_script_and_structured_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("IACAD_WORKSPACE", str(tmp_path))
    script = tmp_path / "pieza.iacs"
    script.write_text("feature.box id=base body=principal length=10mm width=20mm height=5mm\n", encoding="utf-8")
    runner = CliRunner()
    created = runner.invoke(app, ["new", "parts/p.iacad", "--name", "Pieza CLI"])
    assert created.exit_code == 0, created.output
    assert json.loads(created.stdout)["revision"] == 0
    made = runner.invoke(app, ["exec", "parts/p.iacad", "--script", "pieza.iacs", "--expected-revision", "0"])
    assert made.exit_code == 0, made.output
    assert json.loads(made.stdout)["summary"]["volume_mm3"] == 1000
    rejected = runner.invoke(app, ["exec", "parts/p.iacad", "--script", "pieza.iacs", "--expected-revision", "0"])
    assert rejected.exit_code == 2
    assert json.loads(rejected.stdout)["error"]["code"] == "REVISION_CONFLICT"


def test_cli_creates_lathed_part_and_reports_angle_in_degrees(tmp_path, monkeypatch):
    monkeypatch.setenv("IACAD_WORKSPACE", str(tmp_path))
    example = Path(__file__).resolve().parents[1] / "examples" / "casquillo_revolucion.iacs"
    (tmp_path / "casquillo.iacs").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    runner = CliRunner()
    created = runner.invoke(app, ["new", "parts/casquillo.iacad", "--name", "Casquillo"])
    assert created.exit_code == 0, created.output
    result = runner.invoke(app, ["exec", "parts/casquillo.iacad", "--script", "casquillo.iacs"])
    assert result.exit_code == 0, result.output
    assert math.isclose(json.loads(result.stdout)["summary"]["volume_mm3"], math.pi * 1500, abs_tol=1e-5)
    params = runner.invoke(app, ["query", "parts/casquillo.iacad", "params"])
    assert params.exit_code == 0, params.output
    assert json.loads(params.stdout)["parameters_deg"]["giro"] == 360
    help_result = runner.invoke(app, ["help", "feature.revolve"])
    assert help_result.exit_code == 0, help_result.output
    assert json.loads(help_result.stdout)["schema"]["properties"]["axis"]


def test_cli_shell_script_and_help_expose_face_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("IACAD_WORKSPACE", str(tmp_path))
    example = Path(__file__).resolve().parents[1] / "examples" / "caja_vaciada.iacs"
    (tmp_path / "caja.iacs").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["new", "parts/caja.iacad", "--name", "Caja vaciada"]).exit_code == 0
    result = runner.invoke(app, ["exec", "parts/caja.iacad", "--script", "caja.iacs"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["summary"]["volume_mm3"] == 7152
    help_result = runner.invoke(app, ["help", "feature.shell"])
    assert help_result.exit_code == 0, help_result.output
    assert "remove_faces" in json.loads(help_result.stdout)["schema"]["properties"]


def test_cli_loft_sections_and_offset_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("IACAD_WORKSPACE", str(tmp_path))
    example = Path(__file__).resolve().parents[1] / "examples" / "cono_truncado.iacs"
    (tmp_path / "cono.iacs").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["new", "parts/cono.iacad", "--name", "Cono truncado"]).exit_code == 0
    result = runner.invoke(app, ["exec", "parts/cono.iacad", "--script", "cono.iacs"])
    assert result.exit_code == 0, result.output
    assert math.isclose(json.loads(result.stdout)["summary"]["volume_mm3"], math.pi * 20 * 175 / 3, abs_tol=1e-5)
    loft_help = runner.invoke(app, ["help", "feature.loft"])
    sketch_help = runner.invoke(app, ["help", "sketch.new"])
    assert loft_help.exit_code == 0 and sketch_help.exit_code == 0
    assert "sections" in json.loads(loft_help.stdout)["schema"]["properties"]
    assert "offset" in json.loads(sketch_help.stdout)["schema"]["properties"]


def test_cli_pattern_linear_script_and_help(tmp_path, monkeypatch):
    monkeypatch.setenv("IACAD_WORKSPACE", str(tmp_path))
    script = Path(__file__).resolve().parents[1] / "examples" / "placa_patron_lineal.iacs"
    (tmp_path / "patron.iacs").write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["new", "parts/patron.iacad", "--name", "Cuatro taladros"]).exit_code == 0
    executed = runner.invoke(app, ["exec", "parts/patron.iacad", "--script", "patron.iacs"])
    assert executed.exit_code == 0, executed.output
    assert math.isclose(json.loads(executed.stdout)["summary"]["volume_mm3"], 6000 - 80 * math.pi, abs_tol=1e-5)
    help_result = runner.invoke(app, ["help", "feature.pattern_linear"])
    assert help_result.exit_code == 0, help_result.output
    assert {"source", "target", "count", "spacing", "direction"} <= set(json.loads(help_result.stdout)["schema"]["properties"])


def test_cli_pattern_circular_script_and_help(tmp_path, monkeypatch):
    monkeypatch.setenv("IACAD_WORKSPACE", str(tmp_path))
    example = Path(__file__).resolve().parents[1] / "examples" / "brida_patron_circular.iacs"
    (tmp_path / "brida.iacs").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["new", "parts/brida.iacad", "--name", "Brida"]).exit_code == 0
    created = runner.invoke(app, ["exec", "parts/brida.iacad", "--script", "brida.iacs"])
    assert created.exit_code == 0, created.output
    assert math.isclose(json.loads(created.stdout)["summary"]["volume_mm3"], 12500 - 80 * math.pi, abs_tol=1e-5)
    description = runner.invoke(app, ["help", "feature.pattern_circular"])
    assert description.exit_code == 0, description.output
    assert {"axis", "angle", "count", "source"} <= set(json.loads(description.stdout)["schema"]["properties"])


def test_cli_sweep_script_and_path_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("IACAD_WORKSPACE", str(tmp_path))
    example = Path(__file__).resolve().parents[1] / "examples" / "tubo_acodado.iacs"
    (tmp_path / "tubo.iacs").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["new", "parts/tubo.iacad", "--name", "Tubo acodado"]).exit_code == 0
    made = runner.invoke(app, ["exec", "parts/tubo.iacad", "--script", "tubo.iacs"])
    assert made.exit_code == 0, made.output
    assert math.isclose(json.loads(made.stdout)["summary"]["volume_mm3"], 360 * math.pi, abs_tol=1e-5)
    help_result = runner.invoke(app, ["help", "feature.sweep"])
    assert help_result.exit_code == 0, help_result.output
    assert "path" in json.loads(help_result.stdout)["schema"]["properties"]


def test_mcp_stdio_can_create_edit_and_query(tmp_path):
    async def exchange():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "iacad.cli", "mcp"],
            env={**os.environ, "IACAD_WORKSPACE": str(tmp_path)},
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {"help", "session", "exec", "query", "validate", "export", "render"}
            created = await client.call_tool("session", {"action": "new", "doc": "parts/demo.iacad", "name": "Demo MCP"})
            assert created.structuredContent["revision"] == 0
            changed = await client.call_tool("exec", {
                "doc": "parts/demo.iacad",
                "commands": [{"cmd": "feature.box", "args": {"id": "caja", "body": "principal", "length": "10 mm", "width": "10 mm", "height": "10 mm"}}],
                "expected_revision": 0,
            })
            assert changed.structuredContent["summary"]["volume_mm3"] == 1000
            queried = await client.call_tool("query", {"doc": "parts/demo.iacad", "what": "tree"})
            assert queried.structuredContent["features"][0]["id"] == "caja"
            rejected = await client.call_tool("exec", {
                "doc": "parts/demo.iacad",
                "commands": [{"cmd": "feature.unknown", "args": {"id": "f"}}],
            })
            assert rejected.isError
            assert rejected.structuredContent["error"]["code"] == "UNKNOWN_COMMAND"
            undone = await client.call_tool("session", {"action": "undo", "doc": "parts/demo.iacad", "expected_revision": 1})
            assert undone.structuredContent["summary"]["bodies"] == 0
            redone = await client.call_tool("session", {"action": "redo", "doc": "parts/demo.iacad", "expected_revision": 2})
            assert redone.structuredContent["summary"]["volume_mm3"] == 1000
            topology = await client.call_tool("query", {"doc": "parts/demo.iacad", "what": "topology", "body": "principal", "kind": "edge", "limit": 20})
            assert topology.structuredContent["total"] == 12
            assert "@caja/edge:xmax&ymax" in {item["ref"] for item in topology.structuredContent["items"]}
            rounded = await client.call_tool("exec", {
                "doc": "parts/demo.iacad", "expected_revision": 3,
                "commands": [{"cmd": "feature.fillet", "args": {
                    "id": "redondeo", "target": "principal", "radius": "1 mm",
                    "edges": {"refs": ["@caja/edge:xmax&ymax"], "expect": "one"},
                }}],
            })
            assert not rounded.isError
            assert rounded.structuredContent["summary"]["volume_mm3"] < 1000
            project = await client.call_tool("session", {"action": "new", "doc": "proyecto.iacad", "name": "Demo", "kind": "project"})
            assert project.structuredContent["kind"] == "project"
            linked = await client.call_tool("exec", {
                "doc": "proyecto.iacad",
                "commands": [
                    {"cmd": "project.brief", "args": {"summary": "Caja 10 mm"}},
                    {"cmd": "project.link", "args": {"path": "parts/demo.iacad", "uid": created.structuredContent["uid"]}},
                ],
                "expected_revision": 0,
            })
            assert linked.structuredContent["summary"]["documents"] == 1
            brief = await client.call_tool("query", {"doc": "proyecto.iacad", "what": "brief"})
            assert brief.structuredContent["brief"]["summary"] == "Caja 10 mm"
            await client.call_tool("session", {"action": "new", "doc": "parts/croquis.iacad", "name": "Croquis"})
            script = (Path(__file__).resolve().parents[1] / "examples" / "placa_croquis.iacs").read_text(encoding="utf-8")
            sketch = await client.call_tool("exec", {"doc": "parts/croquis.iacad", "script": script, "expected_revision": 0})
            assert not sketch.isError
            assert sketch.structuredContent["summary"]["bodies"] == 1
            assert sketch.structuredContent["summary"]["volume_mm3"] > 6800
            await client.call_tool("session", {"action": "new", "doc": "parts/casquillo.iacad", "name": "Casquillo"})
            revolve_script = (Path(__file__).resolve().parents[1] / "examples" / "casquillo_revolucion.iacs").read_text(encoding="utf-8")
            tube = await client.call_tool("exec", {"doc": "parts/casquillo.iacad", "script": revolve_script})
            assert not tube.isError
            assert math.isclose(tube.structuredContent["summary"]["volume_mm3"], math.pi * 1500, abs_tol=1e-5)
            await client.call_tool("session", {"action": "new", "doc": "parts/caja.iacad", "name": "Caja vaciada"})
            shell_script = (Path(__file__).resolve().parents[1] / "examples" / "caja_vaciada.iacs").read_text(encoding="utf-8")
            hollow = await client.call_tool("exec", {"doc": "parts/caja.iacad", "script": shell_script, "expected_revision": 0})
            assert not hollow.isError
            assert hollow.structuredContent["summary"]["volume_mm3"] == 7152
            verified = await client.call_tool("validate", {"doc": "parts/caja.iacad"})
            assert verified.structuredContent["checks"]["passed"] == 1
            await client.call_tool("session", {"action": "new", "doc": "parts/cono.iacad", "name": "Cono truncado"})
            loft_script = (Path(__file__).resolve().parents[1] / "examples" / "cono_truncado.iacs").read_text(encoding="utf-8")
            cone = await client.call_tool("exec", {"doc": "parts/cono.iacad", "script": loft_script, "expected_revision": 0})
            assert not cone.isError
            assert math.isclose(cone.structuredContent["summary"]["volume_mm3"], math.pi * 20 * 175 / 3, abs_tol=1e-5)
            cone_query = await client.call_tool("query", {"doc": "parts/cono.iacad", "what": "tree"})
            assert [entry["type"] for entry in cone_query.structuredContent["features"]][-1] == "loft"
            await client.call_tool("session", {"action": "new", "doc": "parts/patron.iacad", "name": "Patrón taladros"})
            pattern_script = (Path(__file__).resolve().parents[1] / "examples" / "placa_patron_lineal.iacs").read_text(encoding="utf-8")
            pattern = await client.call_tool("exec", {"doc": "parts/patron.iacad", "script": pattern_script,
                                                      "expected_revision": 0})
            assert not pattern.isError
            assert math.isclose(pattern.structuredContent["summary"]["volume_mm3"], 6000 - 80 * math.pi, abs_tol=1e-5)
            topology = await client.call_tool("query", {"doc": "parts/patron.iacad", "what": "topology", "kind": "face"})
            assert len([face for face in topology.structuredContent["items"] if face["geom_type"] == "CYLINDER"]) == 4
            await client.call_tool("session", {"action": "new", "doc": "parts/brida.iacad", "name": "Brida"})
            circular_script = (Path(__file__).resolve().parents[1] / "examples" / "brida_patron_circular.iacs").read_text(encoding="utf-8")
            flange = await client.call_tool("exec", {"doc": "parts/brida.iacad", "script": circular_script,
                                                     "expected_revision": 0})
            assert not flange.isError
            assert math.isclose(flange.structuredContent["summary"]["volume_mm3"], 12500 - 80 * math.pi, abs_tol=1e-5)
            flange_topology = await client.call_tool("query", {"doc": "parts/brida.iacad", "what": "topology", "kind": "face"})
            assert len([face for face in flange_topology.structuredContent["items"] if face["geom_type"] == "CYLINDER"]) == 4
            await client.call_tool("session", {"action": "new", "doc": "parts/tubo.iacad", "name": "Tubo acodado"})
            sweep_script = (Path(__file__).resolve().parents[1] / "examples" / "tubo_acodado.iacs").read_text(encoding="utf-8")
            tube = await client.call_tool("exec", {"doc": "parts/tubo.iacad", "script": sweep_script, "expected_revision": 0})
            assert not tube.isError
            assert math.isclose(tube.structuredContent["summary"]["volume_mm3"], 360 * math.pi, abs_tol=1e-5)
            assert (tmp_path / "parts/demo.iacad").exists()

    anyio.run(exchange)
