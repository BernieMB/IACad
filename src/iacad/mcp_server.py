"""MCP por stdio. La CLI y las tools usan exactamente el mismo servicio."""

import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image
from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import BaseModel, ConfigDict

from iacad.errors import CadError, failure
from iacad.scripts import parse_script
from iacad.service import CADService

server = FastMCP("iacad", instructions="CAD headless: carga el skill iacad, usa help para descubrir comandos y query/validate para comprobar cada cambio.")
service = CADService()


class ToolEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")
    ok: bool


Result = Annotated[CallToolResult, ToolEnvelope]


def respond(fn) -> CallToolResult:
    try:
        payload = fn()
    except CadError as exc:
        payload = failure(exc)
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=True))],
        structuredContent=payload,
        isError=not payload["ok"],
    )


@server.tool(name="help", description="Lista comandos CAD implementados o muestra el esquema y ejemplo de uno. Consulta antes de diseñar.", structured_output=True)
def help_command(topic: str = "") -> Result:
    return respond(lambda: service.help(topic))


@server.tool(name="session", description="Crea documentos kind=part|project o gestiona revisiones: new|undo|redo|checkpoint|restore|history. Incluye expected_revision.", structured_output=True)
def session(action: str, doc: str, name: str = "", units: str = "mm", kind: str = "part", expected_revision: int | None = None) -> Result:
    def action_fn():
        if action == "new":
            return service.new(doc, name, units, kind)
        if action == "history":
            return service.history(doc)
        if action == "checkpoint":
            return service.checkpoint(doc, name, expected_revision)
        if action in ("undo", "redo", "restore"):
            return service.navigate(doc, action, expected_revision, name)
        raise CadError("UNKNOWN_ACTION", f"Acción de sesión no implementada: {action}")

    return respond(action_fn)


@server.tool(name="exec", description="Aplica comandos JSON (lista {cmd,args}) o script .iacs atómicamente. dry_run valida sin guardar; expected_revision protege ediciones concurrentes.", structured_output=True)
def execute(doc: str, commands: list[dict] | None = None, script: str | None = None, dry_run: bool = False, expected_revision: int | None = None) -> Result:
    def action():
        if (commands is None) == (script is None):
            raise CadError("INVALID_ARGUMENT", "Especifica commands o script, no ambos")
        return service.execute(doc, commands if commands is not None else parse_script(script), dry_run=dry_run, expected_revision=expected_revision)

    return respond(action)


@server.tool(name="query", description="Inspecciona pieza/proyecto: summary, tree, params, brief o topology (caras/aristas con refs y paginación). Cotas en mm.", structured_output=True)
def query(doc: str, what: str = "summary", body: str | None = None, kind: str = "all",
          limit: int = 100, cursor: int = 0) -> Result:
    return respond(lambda: service.query(doc, what, body=body, kind=kind, limit=limit, cursor=cursor))


@server.tool(name="validate", description="Regenera el sólido y devuelve propiedades geométricas y checks sin modificar el documento.", structured_output=True)
def validate(doc: str) -> Result:
    return respond(lambda: service.validate(doc))


@server.tool(name="export", description="Exporta la pieza validada a STEP (exacto), STL/3MF (malla) o GLB (visor), dentro del workspace.", structured_output=True)
def export(doc: str, format: str, out: str) -> Result:
    return respond(lambda: service.export(doc, format, out))


@server.tool(name="render", description="Genera PNG técnico headless, vistas iso/front/top/right/four; devuelve ruta e imagen. No modifica la pieza.", structured_output=True)
def render(doc: str, out: str, views: str = "iso", size: int = 768) -> Result:
    result = respond(lambda: service.render(doc, out, views=views, size=size))
    if not result.isError:
        path = service.root / result.structuredContent["file"]
        image: ImageContent = Image(path=str(path)).to_image_content()
        result.content.append(image)
    return result
