"""Comandos validados y registro extensible (misma capa para CLI y MCP)."""

from collections.abc import Callable
from dataclasses import dataclass
from math import hypot, isfinite
from typing import Annotated, Literal

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
from iacad.sketch import (
    CircleEntity,
    Polyline,
    RectangleEntity,
    RegularPolygonEntity,
    SketchDefinition,
    SlotEntity,
)


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


class MirrorPlane(StrictModel):
    origin: tuple[Quantity, Quantity, Quantity] = (0.0, 0.0, 0.0)
    normal: tuple[float, float, float]

    @model_validator(mode="after")
    def valid_normal(self) -> "MirrorPlane":
        norm = hypot(*self.normal)
        if not all(isfinite(value) for value in self.normal) or not isfinite(norm) or norm <= 1e-6:
            raise ValueError("La normal del plano debe ser finita y no nula")
        return self


class MirrorArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    source: str = Field(pattern=ID_PATTERN)
    body: str = Field(pattern=ID_PATTERN)
    plane: MirrorPlane

    @model_validator(mode="after")
    def separate_output(self) -> "MirrorArgs":
        if self.source == self.body:
            raise ValueError("El cuerpo reflejado debe tener un ID distinto del original")
        return self


class PatternLinearArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    target: str = Field(pattern=ID_PATTERN)
    source: str = Field(pattern=ID_PATTERN)
    op: Literal["cut", "join"] = "cut"
    count: int = Field(ge=2, le=64)
    spacing: Quantity
    direction: tuple[float, float, float] = (1.0, 0.0, 0.0)
    keep_tool: bool = False

    @model_validator(mode="after")
    def valid_direction_and_bodies(self) -> "PatternLinearArgs":
        if self.source == self.target:
            raise ValueError("El cuerpo-herramienta debe ser distinto del destino")
        norm = hypot(*self.direction)
        if not all(isfinite(value) for value in self.direction) or not isfinite(norm) or norm <= 1e-6:
            raise ValueError("La dirección del patrón debe ser finita y no nula")
        return self


class PatternCircularArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    target: str = Field(pattern=ID_PATTERN)
    source: str = Field(pattern=ID_PATTERN)
    op: Literal["cut", "join"] = "cut"
    count: int = Field(ge=2, le=64)
    axis: "RevolveAxis"
    angle: Quantity = "360 deg"
    keep_tool: bool = False

    @model_validator(mode="after")
    def different_bodies(self) -> "PatternCircularArgs":
        if self.source == self.target:
            raise ValueError("El cuerpo-herramienta debe ser distinto del destino")
        return self


class CheckAdd(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    type: Literal["valid_solid", "bbox_max", "volume_min"]
    target: str = Field(pattern=ID_PATTERN)
    value: Quantity | list[Quantity] | None = None
    severity: Literal["error", "warning"] = "error"


class SketchNewArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    plane: Literal["XY", "XZ", "YZ"]
    offset: Quantity = 0.0


class SketchPolylineArgs(Polyline):
    sketch: str = Field(pattern=ID_PATTERN)


class SketchCircleArgs(CircleEntity):
    sketch: str = Field(pattern=ID_PATTERN)


class SketchRectangleArgs(RectangleEntity):
    sketch: str = Field(pattern=ID_PATTERN)


class SketchSlotArgs(SlotEntity):
    sketch: str = Field(pattern=ID_PATTERN)


class SketchPolygonArgs(RegularPolygonEntity):
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
        length = hypot(*self.dir)
        if not all(isfinite(value) for value in self.dir) or not isfinite(length) or length <= 1e-6:
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


class LoftArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    sections: list[Annotated[str, Field(pattern=ID_PATTERN)]] = Field(min_length=2)
    ruled: bool = True
    op: Literal["new_body", "join", "cut", "intersect"] = "new_body"
    body: str | None = Field(default=None, pattern=ID_PATTERN)
    target: str | None = Field(default=None, pattern=ID_PATTERN)

    @model_validator(mode="after")
    def valid_sections_and_target(self) -> "LoftArgs":
        if len(set(self.sections)) != len(self.sections):
            raise ValueError("Las secciones deben referirse a croquis diferentes")
        if self.op == "new_body" and (not self.body or self.target):
            raise ValueError("new_body requiere body y prohíbe target")
        if self.op != "new_body" and (not self.target or self.body):
            raise ValueError("join/cut/intersect requieren target y prohíben body")
        return self


class SweepPath(StrictModel):
    points: list[tuple[Quantity, Quantity, Quantity]] = Field(min_length=2, max_length=64)
    transition: Literal["right", "round"] = "right"


class SweepArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    profile: str = Field(pattern=ID_PATTERN)
    path: SweepPath
    op: Literal["new_body", "join", "cut", "intersect"] = "new_body"
    body: str | None = Field(default=None, pattern=ID_PATTERN)
    target: str | None = Field(default=None, pattern=ID_PATTERN)

    @model_validator(mode="after")
    def operation_target(self) -> "SweepArgs":
        if self.op == "new_body" and (not self.body or self.target):
            raise ValueError("new_body requiere body y prohíbe target")
        if self.op != "new_body" and (not self.target or self.body):
            raise ValueError("join/cut/intersect requieren target y prohíben body")
        return self


class HoleArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    target: str = Field(pattern=ID_PATTERN)
    diameter: Quantity
    axis: RevolveAxis
    mode: Literal["through", "blind"] = "through"
    depth: Quantity | None = None

    @model_validator(mode="after")
    def valid_depth(self) -> "HoleArgs":
        if self.mode == "blind" and self.depth is None:
            raise ValueError("El taladro ciego requiere depth")
        if self.mode == "through" and self.depth is not None:
            raise ValueError("El taladro pasante no admite depth")
        return self


class SplitArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    target: str = Field(pattern=ID_PATTERN)
    plane: MirrorPlane
    keep: Literal["positive", "negative"] = "positive"


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


class ShellArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    target: str = Field(pattern=ID_PATTERN)
    remove_faces: Selection
    thickness: Quantity
    direction: Literal["inward", "outward"] = "inward"


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


@register(
    "feature.mirror", MirrorArgs, "Crea un cuerpo nuevo reflejado sobre un plano global; conserva el original.",
    {"id": "reflejo", "source": "principal", "body": "simetrico",
     "plane": {"origin": [0, 0, 0], "normal": [1, 0, 0]}},
)
def feature_mirror(doc: PartDocument, args: MirrorArgs) -> str:
    if any(feature.id == args.id for feature in doc.features):
        raise CadError("DUPLICATE_ID", "Ya existe una feature con ese ID", path="args.id")
    if args.source not in {body.id for body in doc.bodies}:
        raise CadError("UNKNOWN_BODY", "El espejo requiere un cuerpo original existente", path="args.source")
    if args.body in {body.id for body in doc.bodies}:
        raise CadError("DUPLICATE_ID", "El cuerpo reflejado ya existe", path="args.body")
    doc.features.append(Feature(id=args.id, type="mirror", args=args.model_dump()))
    doc.bodies.append(Body(id=args.body))
    return args.id


@register(
    "feature.pattern_linear", PatternLinearArgs,
    "Repite un cuerpo-herramienta contra un destino (cut/join); incluye la posición original.",
    {"id": "perforaciones", "source": "broca", "target": "principal", "op": "cut", "count": 4,
     "spacing": "12 mm", "direction": [1, 0, 0]},
)
def feature_pattern_linear(doc: PartDocument, args: PatternLinearArgs) -> str:
    return add_pattern(doc, args, "pattern_linear")


@register(
    "feature.pattern_circular", PatternCircularArgs,
    "Repite un cuerpo-herramienta sobre eje global (cut/join); 360 grados no repite el inicio.",
    {"id": "perforaciones", "source": "broca", "target": "principal", "op": "cut", "count": 4,
     "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}, "angle": "360 deg"},
)
def feature_pattern_circular(doc: PartDocument, args: PatternCircularArgs) -> str:
    return add_pattern(doc, args, "pattern_circular")


def add_pattern(doc: PartDocument, args: PatternLinearArgs | PatternCircularArgs, kind: str) -> str:
    if any(feature.id == args.id for feature in doc.features):
        raise CadError("DUPLICATE_ID", "Ya existe una feature con ese ID", path="args.id")
    if args.target not in {body.id for body in doc.bodies} or args.source not in {body.id for body in doc.bodies}:
        raise CadError("UNKNOWN_BODY", "El patrón requiere destino y cuerpo-herramienta existentes", path="args.source")
    doc.features.append(Feature(id=args.id, type=kind, args=args.model_dump()))
    if not args.keep_tool:
        doc.bodies = [body for body in doc.bodies if body.id != args.source]
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
    "sketch.new", SketchNewArgs, "Crea un croquis 2D en XY, XZ o YZ, desplazado sobre su normal.",
    {"id": "perfil", "plane": "XY", "offset": "20 mm"},
)
def sketch_new(doc: PartDocument, args: SketchNewArgs) -> str:
    if any(feature.id == args.id for feature in doc.features):
        raise CadError("DUPLICATE_ID", "Ya existe una feature con ese ID", path="args.id")
    doc.features.append(Feature(id=args.id, type="sketch",
                                args=SketchDefinition(plane=args.plane, offset=args.offset).model_dump()))
    return args.id


def add_entity(doc: PartDocument, args: SketchPolylineArgs | SketchCircleArgs | SketchRectangleArgs | SketchSlotArgs | SketchPolygonArgs) -> str:
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
    "sketch.slot", SketchSlotArgs, "Añade ranura cerrada por longitud total, ancho y giro en su plano.",
    {"sketch": "perfil", "id": "ranura", "center": [20, 15], "length": "20 mm", "width": "6 mm", "angle": "30 deg"},
)
def sketch_slot(doc: PartDocument, args: SketchSlotArgs) -> str:
    return add_entity(doc, args)


@register(
    "sketch.polygon", SketchPolygonArgs, "Añade polígono regular cerrado de 3 a 64 lados con radio a vértices o lados.",
    {"sketch": "perfil", "id": "hexagono", "center": [0, 0], "side_count": 6,
     "radius": "10 mm", "radius_type": "circumradius", "angle": "0 deg"},
)
def sketch_polygon(doc: PartDocument, args: SketchPolygonArgs) -> str:
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


@register(
    "feature.loft", LoftArgs, "Une al menos dos croquis paralelos y ordenados en un sólido.",
    {"id": "transicion", "sections": ["base", "corona"], "ruled": True,
     "op": "new_body", "body": "principal"},
)
def feature_loft(doc: PartDocument, args: LoftArgs) -> str:
    return add_profile_feature(doc, args, "loft")


@register(
    "feature.sweep", SweepArgs, "Barre un croquis cerrado por ruta 3D en segmentos, iniciada en su plano.",
    {"id": "tubo", "profile": "seccion", "path": {"points": [[0, 0, 0], [0, 0, 10], [20, 0, 10]],
                                                  "transition": "right"}, "body": "principal"},
)
def feature_sweep(doc: PartDocument, args: SweepArgs) -> str:
    return add_profile_feature(doc, args, "sweep")


@register(
    "feature.hole", HoleArgs, "Taladra un cuerpo sobre un eje global: pasante o ciego de fondo plano.",
    {"id": "taladro", "target": "principal", "diameter": "8 mm",
     "axis": {"origin": [20, 15, 6], "dir": [0, 0, -1]}, "mode": "blind", "depth": "4 mm"},
)
def feature_hole(doc: PartDocument, args: HoleArgs) -> str:
    return add_dressup(doc, args, "hole")


@register(
    "feature.split", SplitArgs, "Corta un cuerpo con un plano global y conserva el lado positivo o negativo.",
    {"id": "recorte", "target": "principal", "plane": {"origin": [20, 0, 0], "normal": [1, 0, 1]},
     "keep": "positive"},
)
def feature_split(doc: PartDocument, args: SplitArgs) -> str:
    return add_dressup(doc, args, "split")


def add_profile_feature(doc: PartDocument, args: ExtrudeArgs | RevolveArgs | LoftArgs | SweepArgs, kind: str) -> str:
    if any(feature.id == args.id for feature in doc.features):
        raise CadError("DUPLICATE_ID", "Ya existe una feature con ese ID", path="args.id")
    profiles = args.sections if isinstance(args, LoftArgs) else [args.profile]
    if any(not any(feature.id == profile and feature.type == "sketch" for feature in doc.features)
           for profile in profiles):
        raise CadError("UNKNOWN_SKETCH", "La operación necesita croquis anteriores", path="args.sections" if kind == "loft" else "args.profile")
    if args.op == "new_body":
        if any(body.id == args.body for body in doc.bodies):
            raise CadError("DUPLICATE_ID", "El cuerpo de salida ya existe", path="args.body")
        doc.bodies.append(Body(id=args.body))
    elif args.target not in {body.id for body in doc.bodies}:
        raise CadError("UNKNOWN_BODY", "No existe el cuerpo destino", path="args.target")
    doc.features.append(Feature(id=args.id, type=kind, args=args.model_dump(exclude_none=True)))
    return args.id


def add_dressup(doc: PartDocument, args: FilletArgs | ChamferArgs | ShellArgs | HoleArgs | SplitArgs, kind: str) -> str:
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
    "feature.shell", ShellArgs, "Vacía un cuerpo con espesor constante, abriendo las caras seleccionadas.",
    {"id": "vaciado", "target": "principal", "remove_faces": {"refs": ["@base/face:zmax"], "expect": "one"},
     "thickness": "2 mm", "direction": "inward"},
)
def feature_shell(doc: PartDocument, args: ShellArgs) -> str:
    return add_dressup(doc, args, "shell")


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
