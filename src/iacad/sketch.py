"""Croquis 2D acotados por expresiones, en planos estándar explícitos."""

from typing import Annotated, Literal

from build123d import Align, Circle, Plane, Polygon, Pos, Rectangle, Sketch
from pydantic import Field, model_validator

from iacad.errors import CadError
from iacad.model import ID_PATTERN, Quantity, StrictModel
from iacad.units import QuantityEvaluator

Point2 = tuple[Quantity, Quantity]
PLANES = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}


class Polyline(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    type: Literal["polyline"] = "polyline"
    closed: Literal[True] = True
    points: list[Point2] = Field(min_length=3)


class CircleEntity(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    type: Literal["circle"] = "circle"
    center: Point2
    radius: Quantity


class RectangleEntity(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    type: Literal["rectangle"] = "rectangle"
    center: Point2 = (0.0, 0.0)
    width: Quantity
    height: Quantity


SketchEntity = Annotated[Polyline | CircleEntity | RectangleEntity, Field(discriminator="type")]


class SketchDefinition(StrictModel):
    plane: Literal["XY", "XZ", "YZ"]
    offset: Quantity = 0.0
    entities: list[SketchEntity] = Field(default_factory=list)
    profiles: Literal["auto"] = "auto"

    @model_validator(mode="after")
    def unique_entities(self) -> "SketchDefinition":
        ids = [entity.id for entity in self.entities]
        if len(ids) != len(set(ids)):
            raise ValueError("Los IDs de las entidades del croquis deben ser únicos")
        return self


def resolve(definition: SketchDefinition, evaluator: QuantityEvaluator) -> tuple[Sketch | None, dict]:
    """Primer contorno cerrado = exterior; los siguientes = huecos interiores."""

    offset = evaluator.length(definition.offset, path="args.offset")
    plane = PLANES[definition.plane].offset(offset)
    if not definition.entities:
        return None, {"plane": definition.plane, "offset_mm": offset, "entities": []}

    shapes: list[Sketch] = []
    resolved: list[dict] = []
    for entity in definition.entities:
        if isinstance(entity, Polyline):
            points = [tuple(evaluator.length(coord) for coord in point) for point in entity.points]
            if len(set(points)) != len(points):
                raise CadError("PROFILE_INVALID", "La polilínea contiene puntos duplicados", path=entity.id)
            shape = Polygon(*points, align=None)
            geometry = {"type": "polyline", "id": entity.id, "points_mm": points}
        elif isinstance(entity, CircleEntity):
            center = tuple(evaluator.length(coord) for coord in entity.center)
            radius = evaluator.length(entity.radius)
            if radius <= 0:
                raise CadError("INVALID_DIMENSION", "El radio debe ser positivo", path=entity.id)
            shape = Pos(*center) * Circle(radius)
            geometry = {"type": "circle", "id": entity.id, "center_mm": center, "radius_mm": radius}
        else:
            center = tuple(evaluator.length(coord) for coord in entity.center)
            width, height = evaluator.length(entity.width), evaluator.length(entity.height)
            if width <= 0 or height <= 0:
                raise CadError("INVALID_DIMENSION", "El rectángulo requiere ancho y alto positivos", path=entity.id)
            shape = Pos(*center) * Rectangle(width, height, align=(Align.CENTER, Align.CENTER))
            geometry = {"type": "rectangle", "id": entity.id, "center_mm": center, "width_mm": width, "height_mm": height}
        if not shape.is_valid or shape.area <= 0:
            raise CadError("PROFILE_INVALID", "Contorno 2D inválido", path=entity.id)
        shapes.append(shape)
        resolved.append(geometry)

    outer = shapes[0]
    for hole, entity in zip(shapes[1:], definition.entities[1:], strict=True):
        shared = outer & hole
        if abs(shared.area - hole.area) > max(1e-6, hole.area * 1e-7):
            raise CadError("PROFILE_INVALID", "El hueco debe estar totalmente dentro del contorno exterior", path=entity.id)
        outer = outer - hole
    if not outer.is_valid or outer.area <= 0:
        raise CadError("PROFILE_INVALID", "Croquis sin una región cerrada válida")
    return plane * outer, {"plane": definition.plane, "offset_mm": offset, "entities": resolved}
