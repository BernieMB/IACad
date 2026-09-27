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
            assert (tmp_path / "parts/demo.iacad").exists()

    anyio.run(exchange)
