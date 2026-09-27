"""Capturas técnicas deterministas sin contexto gráfico y entrega por MCP."""

import os
import sys

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from PIL import Image as PILImage
from typer.testing import CliRunner

from iacad.cli import app
from iacad.errors import CadError
from iacad.service import CADService


@pytest.fixture
def piece(tmp_path):
    cad = CADService(root=tmp_path)
    cad.new("parts/placa.iacad", "Placa")
    cad.execute("parts/placa.iacad", [
        {"cmd": "feature.box", "args": {"id": "base", "body": "principal", "length": 40, "width": 30, "height": 6}},
        {"cmd": "feature.cylinder", "args": {"id": "broca", "body": "tool", "radius": 4, "height": 6, "origin": [20, 15, 0]}},
        {"cmd": "feature.boolean", "args": {"id": "hole", "op": "cut", "target": "principal", "tools": ["tool"]}},
    ])
    return cad


def test_png_named_views_and_four_view_sheet_are_real_images(piece, tmp_path):
    for name in ("iso", "front", "top", "right", "four"):
        file = f"out/{name}.png"
        result = piece.render("parts/placa.iacad", file, views=name, size=384)
        assert result["revision"] == 1
        assert result["cache"] == {"hits": 3, "misses": 0}
        assert (tmp_path / file).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        with PILImage.open(tmp_path / file) as image:
            assert image.size == (384, 384)
            assert image.getbbox()
            assert len(image.getcolors(maxcolors=1_000_000)) > 2
    assert (tmp_path / "parts/placa.iacad").exists()


def test_render_rejects_bad_path_and_view_without_touching_document(piece, tmp_path):
    before = (tmp_path / "parts/placa.iacad").read_bytes()
    with pytest.raises(CadError) as error:
        piece.render("parts/placa.iacad", "../outside.png")
    assert error.value.code == "PATH_OUTSIDE_WORKSPACE"
    with pytest.raises(CadError) as error:
        piece.render("parts/placa.iacad", "out/invalid.png", views="fake")
    assert error.value.code == "INVALID_ARGUMENT"
    assert not (tmp_path / "out/invalid.png").exists()
    assert before == (tmp_path / "parts/placa.iacad").read_bytes()


def test_cli_render_outputs_json_and_png(piece, tmp_path, monkeypatch):
    monkeypatch.setenv("IACAD_WORKSPACE", str(tmp_path))
    result = CliRunner().invoke(app, [
        "render", "parts/placa.iacad", "--out", "out/cli.png", "--views", "top", "--size", "384",
    ])
    assert result.exit_code == 0, result.output
    assert '"views": "top"' in result.stdout
    assert (tmp_path / "out/cli.png").is_file()


def test_mcp_render_returns_png_and_structured_result(piece, tmp_path):
    async def exchange():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "iacad.cli", "mcp"],
            env={**os.environ, "IACAD_WORKSPACE": str(tmp_path)},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            await client.initialize()
            result = await client.call_tool("render", {
                "doc": "parts/placa.iacad", "out": "out/mcp-preview.png", "views": "four", "size": 384,
            })
            assert not result.isError
            assert result.structuredContent["file"] == "out/mcp-preview.png"
            assert any(item.type == "image" and item.mimeType == "image/png" for item in result.content)
            assert (tmp_path / "out/mcp-preview.png").exists()

    anyio.run(exchange)
