"""CLI headless: una respuesta JSON por operación, diagnósticos en stderr."""

import json
from collections.abc import Callable
from typing import Annotated

import typer

from iacad.errors import CadError, failure
from iacad.model import DOCUMENT_ADAPTER
from iacad.service import CADService
from iacad.storage import safe_path

app = typer.Typer(add_completion=False, no_args_is_help=True, help="CAD headless para agentes de IA")


def run(action: Callable[[], dict]) -> None:
    try:
        result = action()
        typer.echo(json.dumps(result, ensure_ascii=True, allow_nan=False))
        if not result.get("ok", True):
            raise typer.Exit(code=2)
    except CadError as exc:
        typer.echo(json.dumps(failure(exc), ensure_ascii=True))
        raise typer.Exit(code=3 if exc.code in ("GEOMETRY_FAILED", "INVALID_GEOMETRY", "EXPORT_FAILED") else 2) from exc
    except OSError as exc:
        typer.echo(json.dumps(failure(CadError("IO_ERROR", str(exc))), ensure_ascii=True))
        raise typer.Exit(code=4) from exc


@app.command("new")
def new(path: str, name: Annotated[str, typer.Option(help="Nombre legible")], units: str = "mm", kind: str = "part") -> None:
    run(lambda: CADService().new(path, name, units, kind))


def read_commands(commands: str | None, script: str | None) -> list[dict]:
    from iacad.scripts import parse_script

    if (commands is None) == (script is None):
        raise CadError("INVALID_ARGUMENT", "Especifica exactamente uno de --commands o --script")
    if script is not None:
        try:
            return parse_script(safe_path(script).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CadError("SCRIPT_NOT_FOUND", "No se encuentra el script", path=script) from exc
    try:
        value = json.loads(commands)
    except json.JSONDecodeError as exc:
        raise CadError("INVALID_COMMAND", "--commands no contiene JSON válido", hint=str(exc)) from exc
    if not isinstance(value, list):
        raise CadError("INVALID_COMMAND", "--commands debe ser un array JSON")
    return value


@app.command("exec")
def execute(
    path: str,
    commands: Annotated[str | None, typer.Option(help="Lista JSON de comandos")] = None,
    script: Annotated[str | None, typer.Option(help="Ruta .iacs dentro del workspace")] = None,
    dry_run: bool = False,
    expected_revision: int | None = None,
) -> None:
    run(lambda: CADService().execute(path, read_commands(commands, script), dry_run=dry_run, expected_revision=expected_revision))


@app.command("validate")
def validate(path: str, script: str | None = None) -> None:
    def action():
        service = CADService()
        if script:
            return service.execute(path, read_commands(None, script), dry_run=True)
        return service.validate(path)

    run(action)


@app.command("query")
def query(path: str, what: Annotated[str, typer.Argument(help="summary|tree|params|brief|topology")] = "summary", body: str | None = None, kind: str = "all",
          limit: int = 100, cursor: int = 0) -> None:
    run(lambda: CADService().query(path, what, body=body, kind=kind, limit=limit, cursor=cursor))


@app.command("export")
def export(path: str, format: Annotated[str, typer.Option()], out: Annotated[str, typer.Option()]) -> None:
    run(lambda: CADService().export(path, format, out))


@app.command("render")
def render(path: str, out: Annotated[str, typer.Option()], views: str = "iso", size: int = 768) -> None:
    run(lambda: CADService().render(path, out, views=views, size=size))


@app.command("help")
def command_help(topic: Annotated[str, typer.Argument(help="Nombre del comando CAD (opcional)")] = "") -> None:
    run(lambda: CADService().help(topic))


@app.command("schema")
def schema() -> None:
    run(lambda: {"ok": True, "schema": DOCUMENT_ADAPTER.json_schema()})


@app.command("history")
def history(path: str) -> None:
    run(lambda: CADService().history(path))


@app.command("undo")
def undo(path: str, expected_revision: int | None = None) -> None:
    run(lambda: CADService().navigate(path, "undo", expected_revision))


@app.command("redo")
def redo(path: str, expected_revision: int | None = None) -> None:
    run(lambda: CADService().navigate(path, "redo", expected_revision))


@app.command("checkpoint")
def checkpoint(path: str, name: str, expected_revision: int | None = None) -> None:
    run(lambda: CADService().checkpoint(path, name, expected_revision))


@app.command("restore")
def restore(path: str, name: str, expected_revision: int | None = None) -> None:
    run(lambda: CADService().navigate(path, "restore", expected_revision, name))


@app.command("mcp")
def mcp() -> None:
    from iacad.mcp_server import server

    server.run(transport="stdio")


if __name__ == "__main__":
    app()
