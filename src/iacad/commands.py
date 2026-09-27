"""Comandos validados y registro extensible (misma capa para CLI y MCP)."""

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from iacad.errors import CadError
from iacad.model import (
    ID_PATTERN,
    Body,
    Document,
    DocumentRef,
    Feature,
    Parameter,
    PartDocument,
    ProjectDocument,
    Quantity,
    Requirement,
    StrictModel,
)
from iacad.naming import Selection
from iacad.sketch import CircleEntity, Polyline, RectangleEntity, SketchDefinition


class ParamSet(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: Quantity
    kind: Literal["length", "angle"] = "length"
    min: Quantity | None = None
    max: Quantity | None = None
    description: str = ""


class BoxArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    body: str = Field(pattern=ID_PATTERN)
    length: Quantity
    width: Quantity
    height: Quantity
    origin: list[Quantity] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)


class CylinderArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    body: str = Field(pattern=ID_PATTERN)
    radius: Quantity
    height: Quantity
    origin: list[Quantity] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)


class BooleanArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    op: Literal["cut", "union", "intersect"]
    target: str = Field(pattern=ID_PATTERN)
    tools: list[str] = Field(min_length=1)
    keep_tools: bool = False


class CheckAdd(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    type: Literal["valid_solid", "bbox_max", "volume_min"]
    target: str = Field(pattern=ID_PATTERN)
    value: Quantity | list[Quantity] | None = None
    severity: Literal["error", "warning"] = "error"


class SketchNewArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    plane: Literal["XY", "XZ", "YZ"]


class SketchPolylineArgs(Polyline):
    sketch: str = Field(pattern=ID_PATTERN)


class SketchCircleArgs(CircleEntity):
    sketch: str = Field(pattern=ID_PATTERN)


class SketchRectangleArgs(RectangleEntity):
    sketch: str = Field(pattern=ID_PATTERN)


class ExtrudeExtent(StrictModel):
    type: Literal["distance", "symmetric"] = "distance"
    distance: Quantity


class ExtrudeArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    profile: str = Field(pattern=ID_PATTERN)
    extent: ExtrudeExtent
    direction: Literal["normal", "reverse"] = "normal"
    op: Literal["new_body", "join", "cut", "intersect"] = "new_body"
    body: str | None = Field(default=None, pattern=ID_PATTERN)
    target: str | None = Field(default=None, pattern=ID_PATTERN)

    @model_validator(mode="after")
    def operation_target(self) -> "ExtrudeArgs":
        if self.op == "new_body" and (not self.body or self.target):
            raise ValueError("new_body requiere body y prohíbe target")
        if self.op != "new_body" and (not self.target or self.body):
            raise ValueError("join/cut/intersect requieren target y prohíben body")
        if self.extent.type == "symmetric" and self.direction == "reverse":
            raise ValueError("La extrusión simétrica no admite reverse")
        return self


class RevolveAxis(StrictModel):
    origin: tuple[Quantity, Quantity, Quantity] = (0.0, 0.0, 0.0)
    dir: tuple[float, float, float]

    @model_validator(mode="after")
    def valid_direction(self) -> "RevolveAxis":
        if not all(isfinite(value) for value in self.dir) or sum(value * value for value in self.dir) <= 1e-12:
            raise ValueError("El eje debe tener una dirección 3D finita y no nula")
        return self


class RevolveArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    profile: str = Field(pattern=ID_PATTERN)
    axis: RevolveAxis
    angle: Quantity = "360 deg"
    op: Literal["new_body", "join", "cut", "intersect"] = "new_body"
    body: str | None = Field(default=None, pattern=ID_PATTERN)
    target: str | None = Field(default=None, pattern=ID_PATTERN)

    @model_validator(mode="after")
    def operation_target(self) -> "RevolveArgs":
        if self.op == "new_body" and (not self.body or self.target):
            raise ValueError("new_body requiere body y prohíbe target")
        if self.op != "new_body" and (not self.target or self.body):
            raise ValueError("join/cut/intersect requieren target y prohíben body")
        return self


class FilletArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    target: str = Field(pattern=ID_PATTERN)
    edges: Selection
    radius: Quantity


class ChamferArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    target: str = Field(pattern=ID_PATTERN)
    edges: Selection
    distance: Quantity


class ProjectBriefArgs(StrictModel):
    summary: str = Field(min_length=1)
    assumptions: list[str] | None = None
    open_questions: list[str] | None = None


class ProjectRequirementArgs(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,62}$")
    text: str = Field(min_length=1)
    verified_by: list[str] | None = None


class ProjectLinkArgs(DocumentRef):
    pass


class ProjectUnlinkArgs(StrictModel):
    path: str = Field(min_length=1)


@dataclass(frozen=True)
class CommandSpec:
    args: type[StrictModel]
    apply: Callable[[Document, StrictModel], str]
    description: str
    example: dict
    kinds: tuple[str, ...]


COMMANDS: dict[str, CommandSpec] = {}


def register(
    name: str,
    args: type[StrictModel],
    description: str,
    example: dict,
    *,
    kinds: tuple[str, ...] = ("part",),
):
    """Extensión por plugins sin tocar el despachador de comandos."""

    def decorate(fn: Callable[[Document, StrictModel], str]):
        if name in COMMANDS:
            raise ValueError(f"Comando duplicado: {name}")
        COMMANDS[name] = CommandSpec(args, fn, description, example, kinds)
        return fn

    return decorate


@register(
    "param.set", ParamSet, "Crear o actualizar un parámetro de longitud o ángulo (kind=angle).",
    {"name": "espesor", "value": "6 mm"}, kinds=("part", "project"),
)
def param_set(doc: Document, args: ParamSet) -> str:
    for index, old in enumerate(doc.parameters):
        if old.name == args.name:
            payload = args.model_dump()
            if "kind" not in args.model_fields_set:
                payload["kind"] = old.kind
            doc.parameters[index] = Parameter(**payload)
            return args.name
    doc.parameters.append(Parameter(**args.model_dump()))
    return args.name


def add_body(doc: PartDocument, args: BoxArgs | CylinderArgs, kind: str) -> str:
    if any(f.id == args.id for f in doc.features):
        raise CadError("DUPLICATE_ID", f"La feature {args.id} ya existe", path="args.id")
    if any(b.id == args.body for b in doc.bodies):
        raise CadError("DUPLICATE_ID", f"El cuerpo {args.body} ya existe", path="args.body")
    doc.features.append(Feature(id=args.id, type=kind, args=args.model_dump()))
    doc.bodies.append(Body(id=args.body))
    return args.id


@register("feature.box", BoxArgs, "Crear un prisma con origen en su esquina inferior.", {"id": "base", "body": "principal", "length": "40 mm", "width": "30 mm", "height": "6 mm"})
def feature_box(doc: PartDocument, args: BoxArgs) -> str:
    return add_body(doc, args, "box")


@register("feature.cylinder", CylinderArgs, "Crear un cilindro vertical (base en origin).", {"id": "broca", "body": "herramienta", "radius": "4 mm", "height": "6 mm", "origin": [20, 15, 0]})
def feature_cylinder(doc: PartDocument, args: CylinderArgs) -> str:
    return add_body(doc, args, "cylinder")


@register("feature.boolean", BooleanArgs, "Aplicar cut, union o intersect a cuerpos.", {"id": "agujero", "op": "cut", "target": "principal", "tools": ["herramienta"]})
def feature_boolean(doc: PartDocument, args: BooleanArgs) -> str:
    if any(f.id == args.id for f in doc.features):
        raise CadError("DUPLICATE_ID", f"La feature {args.id} ya existe", path="args.id")
    live = {body.id for body in doc.bodies}
    if args.target not in live or any(t not in live or t == args.target for t in args.tools):
        raise CadError("UNKNOWN_BODY", "La booleana requiere un destino y herramientas distintos y existentes", path="args.tools")
    if len(set(args.tools)) != len(args.tools):
        raise CadError("DUPLICATE_ID", "Las herramientas booleanas se repiten", path="args.tools")
    doc.features.append(Feature(id=args.id, type="boolean", args=args.model_dump()))
    if not args.keep_tools:
        doc.bodies = [body for body in doc.bodies if body.id not in args.tools]
    return args.id


@register("check.add", CheckAdd, "Añadir comprobación geométrica al documento.", {"id": "ancho_max", "type": "bbox_max", "target": "principal", "value": [50, 50, 10]})
def check_add(doc: PartDocument, args: CheckAdd) -> str:
    if any(check["id"] == args.id for check in doc.checks):
        raise CadError("DUPLICATE_ID", f"El check {args.id} ya existe", path="args.id")
    if args.target not in {b.id for b in doc.bodies}:
        raise CadError("UNKNOWN_BODY", "El check requiere un cuerpo existente", path="args.target")
    if args.type == "bbox_max" and (not isinstance(args.value, list) or len(args.value) != 3):
        raise CadError("INVALID_ARGUMENT", "bbox_max requiere value=[x,y,z]", path="args.value")
    if args.type == "volume_min" and (args.value is None or isinstance(args.value, list)):
        raise CadError("INVALID_ARGUMENT", "volume_min requiere un volumen numérico en mm^3", path="args.value")
    doc.checks.append(args.model_dump(exclude_none=True))
    return args.id


@register(
    "sketch.new", SketchNewArgs, "Crea un croquis 2D en plano XY, XZ o YZ.",
    {"id": "perfil", "plane": "XY"},
)
def sketch_new(doc: PartDocument, args: SketchNewArgs) -> str:
    if any(feature.id == args.id for feature in doc.features):
        raise CadError("DUPLICATE_ID", "Ya existe una feature con ese ID", path="args.id")
    doc.features.append(Feature(id=args.id, type="sketch", args=SketchDefinition(plane=args.plane).model_dump()))
    return args.id


def add_entity(doc: PartDocument, args: SketchPolylineArgs | SketchCircleArgs | SketchRectangleArgs) -> str:
    sketch = next((feature for feature in doc.features if feature.id == args.sketch and feature.type == "sketch"), None)
    if sketch is None:
        raise CadError("UNKNOWN_SKETCH", "El croquis no existe", path="args.sketch")
    if any(entity["id"] == args.id for entity in sketch.args["entities"]):
        raise CadError("DUPLICATE_ID", "ID de entidad repetido dentro del croquis", path="args.id")
    sketch.args["entities"].append(args.model_dump(exclude={"sketch"}))
    return f"{args.sketch}.{args.id}"


@register(
    "sketch.polyline", SketchPolylineArgs, "Añade polilínea cerrada como contorno 2D.",
    {"sketch": "perfil", "id": "exterior", "points": [[0, 0], [40, 0], [40, 30], [0, 30]]},
)
def sketch_polyline(doc: PartDocument, args: SketchPolylineArgs) -> str:
    return add_entity(doc, args)


@register(
    "sketch.circle", SketchCircleArgs, "Añade círculo cerrado; si sigue al exterior, es un hueco.",
    {"sketch": "perfil", "id": "orificio", "center": [20, 15], "radius": "4 mm"},
)
def sketch_circle(doc: PartDocument, args: SketchCircleArgs) -> str:
    return add_entity(doc, args)


@register(
    "sketch.rectangle", SketchRectangleArgs, "Añade rectángulo por centro, ancho y alto.",
    {"sketch": "perfil", "id": "exterior", "center": [20, 15], "width": "40 mm", "height": "30 mm"},
)
def sketch_rectangle(doc: PartDocument, args: SketchRectangleArgs) -> str:
    return add_entity(doc, args)


@register(
    "feature.extrude", ExtrudeArgs, "Extruye un croquis cerrado (distancia o simétrica).",
    {"id": "cuerpo", "profile": "perfil", "extent": {"type": "distance", "distance": "6 mm"},
     "op": "new_body", "body": "principal"},
)
def feature_extrude(doc: PartDocument, args: ExtrudeArgs) -> str:
    return add_profile_feature(doc, args, "extrude")


@register(
    "feature.revolve", RevolveArgs, "Revoluciona un croquis sobre un eje en su plano (ángulo 0..360°).",
    {"id": "casquillo", "profile": "perfil", "axis": {"origin": [0, 0, 0], "dir": [0, 1, 0]},
     "angle": "360 deg", "op": "new_body", "body": "principal"},
)
def feature_revolve(doc: PartDocument, args: RevolveArgs) -> str:
    return add_profile_feature(doc, args, "revolve")


def add_profile_feature(doc: PartDocument, args: ExtrudeArgs | RevolveArgs, kind: str) -> str:
    if any(feature.id == args.id for feature in doc.features):
        raise CadError("DUPLICATE_ID", "Ya existe una feature con ese ID", path="args.id")
    if not any(feature.id == args.profile and feature.type == "sketch" for feature in doc.features):
        raise CadError("UNKNOWN_SKETCH", "La operación necesita un croquis anterior", path="args.profile")
    if args.op == "new_body":
        if any(body.id == args.body for body in doc.bodies):
            raise CadError("DUPLICATE_ID", "El cuerpo de salida ya existe", path="args.body")
        doc.bodies.append(Body(id=args.body))
    elif args.target not in {body.id for body in doc.bodies}:
        raise CadError("UNKNOWN_BODY", "No existe el cuerpo destino", path="args.target")
    doc.features.append(Feature(id=args.id, type=kind, args=args.model_dump(exclude_none=True)))
    return args.id


def add_dressup(doc: PartDocument, args: FilletArgs | ChamferArgs, kind: str) -> str:
    if any(feature.id == args.id for feature in doc.features):
        raise CadError("DUPLICATE_ID", "Ya existe una feature con ese ID", path="args.id")
    if args.target not in {body.id for body in doc.bodies}:
        raise CadError("UNKNOWN_BODY", "La operación necesita un cuerpo existente", path="args.target")
    doc.features.append(Feature(id=args.id, type=kind, args=args.model_dump(exclude_none=True)))
    return args.id


@register(
    "feature.fillet", FilletArgs, "Redondea aristas seleccionadas con radio constante.",
    {"id": "radio", "target": "principal", "edges": {"refs": ["@base/edge:xmax&ymax"], "expect": "one"}, "radius": "2 mm"},
)
def feature_fillet(doc: PartDocument, args: FilletArgs) -> str:
    return add_dressup(doc, args, "fillet")


@register(
    "feature.chamfer", ChamferArgs, "Achaflana aristas seleccionadas con distancia constante.",
    {"id": "chaflan", "target": "principal", "edges": {"query": {"scope": "principal", "kind": "edge", "where": "|Z and >X and >Y"}, "expect": "one"}, "distance": "1 mm"},
)
def feature_chamfer(doc: PartDocument, args: ChamferArgs) -> str:
    return add_dressup(doc, args, "chamfer")


@register(
    "project.brief", ProjectBriefArgs, "Define el resumen y supuestos del encargo.",
    {"summary": "Placa con orificio Ø8 mm"}, kinds=("project",),
)
def project_brief(doc: ProjectDocument, args: ProjectBriefArgs) -> str:
    doc.brief.summary = args.summary
    if args.assumptions is not None:
        doc.brief.assumptions = args.assumptions
    if args.open_questions is not None:
        doc.brief.open_questions = args.open_questions
    return "brief"


@register(
    "project.requirement", ProjectRequirementArgs, "Crea o actualiza un requisito trazable (verified_by opcional).",
    {"id": "REQ-1", "text": "Placa de 40 × 30 × 6 mm", "verified_by": ["parts/placa.iacad#check:cotas"]},
    kinds=("project",),
)
def project_requirement(doc: ProjectDocument, args: ProjectRequirementArgs) -> str:
    for item in doc.brief.requirements:
        if item.id == args.id:
            item.text = args.text
            if args.verified_by is not None:
                item.verified_by = args.verified_by
            return args.id
    doc.brief.requirements.append(Requirement(id=args.id, text=args.text, verified_by=args.verified_by or []))
    return args.id


@register(
    "project.link", ProjectLinkArgs, "Crea o actualiza un enlace a pieza por ruta y UID.",
    {"path": "parts/placa.iacad", "uid": "01JB2X7R9QK4M8N6P3S5T7V9W1", "kind": "part"},
    kinds=("project",),
)
def project_link(doc: ProjectDocument, args: ProjectLinkArgs) -> str:
    for index, item in enumerate(doc.documents):
        if item.path == args.path:
            doc.documents[index] = DocumentRef.model_validate(args.model_dump())
            return args.path
    doc.documents.append(DocumentRef.model_validate(args.model_dump()))
    return args.path


@register(
    "project.unlink", ProjectUnlinkArgs, "Elimina un enlace a pieza que ya no forma parte del proyecto.",
    {"path": "parts/obsoleta.iacad"}, kinds=("project",),
)
def project_unlink(doc: ProjectDocument, args: ProjectUnlinkArgs) -> str:
    if not any(item.path == args.path for item in doc.documents):
        raise CadError("UNKNOWN_DOCUMENT", "La pieza no está enlazada", path="args.path")
    doc.documents = [item for item in doc.documents if item.path != args.path]
    return args.path


def apply(doc: Document, command: dict) -> str:
    if not isinstance(command, dict) or set(command) != {"cmd", "args"}:
        raise CadError("INVALID_COMMAND", "Cada comando debe ser {cmd, args}")
    name = command["cmd"]
    spec = COMMANDS.get(name) if isinstance(name, str) else None
    if spec is None:
        raise CadError("UNKNOWN_COMMAND", f"Comando no implementado: {name}", hint="Consulta iacad help")
    if doc.kind not in spec.kinds:
        raise CadError("WRONG_DOCUMENT_KIND", f"{name} no es válido para un documento {doc.kind}", path="cmd")
    try:
        args = spec.args.model_validate(command["args"])
    except ValidationError as exc:
        raise CadError("INVALID_ARGUMENT", f"Argumentos no válidos para {name}", hint=str(exc)) from exc
    return spec.apply(doc, args)


def help_for(name: str = "") -> dict:
    if name:
        spec = COMMANDS.get(name)
        if spec is None:
            raise CadError("UNKNOWN_COMMAND", f"Comando no implementado: {name}")
        return {"name": name, "description": spec.description, "kinds": spec.kinds, "example": {"cmd": name, "args": spec.example}, "schema": spec.args.model_json_schema()}
    return {"commands": [{"name": name, "description": spec.description, "kinds": spec.kinds} for name, spec in COMMANDS.items()]}
