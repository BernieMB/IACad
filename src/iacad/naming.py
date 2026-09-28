"""Nombres de caras/aristas verificables y selectores geométricos básicos.

No se inventan índices OCCT persistentes: si una edición parte o elimina una
entidad, la selección falla en vez de apuntar silenciosamente a otra.
"""

import re
from typing import Literal

from build123d import CenterOf, Edge, Face, GeomType, Shape
from pydantic import Field, model_validator

from iacad.errors import CadError
from iacad.model import ID_PATTERN, PartDocument, StrictModel

AXES = "XYZ"
_REF = re.compile(rf"^@(?P<feature>{ID_PATTERN[1:-1]})/(?P<kind>edge|face):(?P<role>[a-z0-9_&]+)$")
_RANGE = re.compile(r"^(\d+)\.\.(\d+)$")
_QUERY = re.compile(r"^([<>|#+-][XYZ]|%(?:PLANE|CYLINDER|LINE|CIRCLE))$")


class TopologyQuery(StrictModel):
    scope: str = Field(pattern=ID_PATTERN)
    kind: Literal["edge", "face"]
    where: str = Field(min_length=1)


class Selection(StrictModel):
    refs: list[str] | None = Field(default=None, min_length=1)
    query: TopologyQuery | None = None
    expect: str | int

    @model_validator(mode="after")
    def check(self) -> "Selection":
        if (self.refs is None) == (self.query is None):
            raise ValueError("Indica exactamente refs o query")
        if self.refs and len(self.refs) != len(set(self.refs)):
            raise ValueError("Las referencias no se pueden repetir")
        if isinstance(self.expect, bool):
            raise ValueError("expect debe ser un entero o rango")  # noqa: TRY004 - Pydantic convierte ValueError a ValidationError
        if isinstance(self.expect, int):
            valid = self.expect >= 1
        else:
            match = _RANGE.fullmatch(self.expect)
            valid = self.expect in ("one", "at_least_one") or bool(match and 1 <= int(match[1]) <= int(match[2]))
        if not valid:
            raise ValueError("expect requiere one, at_least_one, N o rango 2..4")
        return self


def origins(document: PartDocument) -> dict[str, tuple[str, str]]:
    """Relaciona cuerpos vivos con la feature que los creó (sin depender del índice OCC)."""

    result: dict[str, tuple[str, str]] = {}
    for feature in document.features:
        args = feature.args
        if feature.type in ("box", "cylinder") or (feature.type in ("extrude", "revolve", "loft", "sweep") and args["op"] == "new_body"):
            result[args["body"]] = (feature.id, feature.type)
        elif feature.type == "boolean":
            if args["op"] != "cut":
                result.pop(args["target"], None)
            if not args["keep_tools"]:
                for tool in args["tools"]:
                    result.pop(tool, None)
        elif feature.type == "mirror":
            result.pop(args["body"], None)
        elif feature.type in ("pattern_linear", "pattern_circular"):
            result.pop(args["target"], None)
            if not args["keep_tool"]:
                result.pop(args["source"], None)
        elif feature.type in ("shell", "sweep", "hole", "split"):
            result.pop(args["target"], None)
        elif feature.type not in ("sketch", "extrude", "revolve", "loft", "sweep", "fillet", "chamfer", "shell", "boolean", "pattern_linear", "pattern_circular"):
            # Un plugin puede modificar cualquier cuerpo: no atribuirle caras de origen.
            result.clear()
    return result


def _coords(shape: Shape) -> tuple[list[float], list[float]]:
    box = shape.bounding_box()
    return [box.min.X, box.min.Y, box.min.Z], [box.max.X, box.max.Y, box.max.Z]


def _tol(shape: Shape) -> float:
    low, high = _coords(shape)
    return max(1e-6, max(b - a for a, b in zip(low, high, strict=True)) * 1e-7)


def _roles(shape: Shape, kind: Literal["face", "edge"], origin: tuple[str, str] | None):
    """Mapea roles del prisma por cotas y normales; roles ambiguos NO se publican."""

    if origin is None:
        return {}
    feature_id, primitive = origin
    low, high = _coords(shape)
    tol = _tol(shape)
    candidates: dict[str, list[Face | Edge]] = {}
    entities = shape.faces() if kind == "face" else shape.edges()
    for entity in entities:
        if primitive == "box":
            if kind == "face" and entity.geom_type == GeomType.PLANE:
                normal = entity.normal_at()
                for index, axis in enumerate(AXES):
                    center = tuple(entity.center(CenterOf.MASS))[index]
                    for direction, bound, sign in (("min", low[index], -1), ("max", high[index], 1)):
                        if abs(center - bound) <= tol and abs(tuple(normal)[index] - sign) <= 1e-5:
                            name = f"@{feature_id}/face:{axis.lower()}{direction}"
                            candidates.setdefault(name, []).append(entity)
            elif kind == "edge" and entity.geom_type == GeomType.LINE:
                edge_low, edge_high = _coords(entity)
                role: list[str] = []
                for index, axis in enumerate(AXES):
                    for direction, bound in (("min", low[index]), ("max", high[index])):
                        if abs(edge_low[index] - bound) <= tol and abs(edge_high[index] - bound) <= tol:
                            role.append(axis.lower() + direction)
                if len(role) == 2:
                    name = f"@{feature_id}/edge:{'&'.join(role)}"
                    candidates.setdefault(name, []).append(entity)
        elif primitive == "cylinder" and kind == "face":
            if entity.geom_type == GeomType.CYLINDER:
                role = "side"
            elif entity.geom_type == GeomType.PLANE:
                center_z = entity.center(CenterOf.MASS).Z
                normal = entity.normal_at().Z
                role = "top" if abs(center_z - high[2]) <= tol and normal > 0.99 else (
                    "bottom" if abs(center_z - low[2]) <= tol and normal < -0.99 else None
                )
            else:
                role = None
            if role:
                name = f"@{feature_id}/face:{role}"
                candidates.setdefault(name, []).append(entity)
    return {name: entries[0] for name, entries in candidates.items() if len(entries) == 1}


def _geometric_query(shape: Shape, kind: Literal["face", "edge"], where: str):
    entities = list(shape.edges() if kind == "edge" else shape.faces())
    for token in where.split(" and "):
        if not _QUERY.fullmatch(token):
            raise CadError("INVALID_SELECTOR", f"Selector no implementado: {token}", hint="Usa |Z, >X, <Z, +Z, -Z, #Z o %PLANE/%LINE, unidos con ' and '")
        if token.startswith("%"):
            if (kind == "edge" and token in ("%PLANE", "%CYLINDER")) or (kind == "face" and token in ("%LINE", "%CIRCLE")):
                raise CadError("INVALID_SELECTOR", f"{token} no corresponde a {kind}s")
            geom_type = getattr(GeomType, token[1:])
            entities = [entity for entity in entities if entity.geom_type == geom_type]
            continue
        operator, axis = token[0], AXES.index(token[1])
        if operator in "><":
            if entities:
                coordinate = [tuple(entity.center(CenterOf.MASS))[axis] for entity in entities]
                extreme = max(coordinate) if operator == ">" else min(coordinate)
                tol = _tol(shape)
                entities = [entity for entity, value in zip(entities, coordinate, strict=True) if abs(value - extreme) <= tol]
            continue
        if operator in "|#+-":
            if operator in "+-" and kind != "face":
                raise CadError("INVALID_SELECTOR", f"{operator}{token[1]} solo está definido para caras")
            if kind == "edge":
                entities = [entity for entity in entities if entity.geom_type == GeomType.LINE]
                values = [abs(tuple(entity.tangent_at(0.5))[axis]) for entity in entities]
            else:
                values = [tuple(entity.normal_at())[axis] for entity in entities]
            if operator == "|":
                entities = [entity for entity, value in zip(entities, values, strict=True) if abs(value) >= 1 - 1e-5]
            elif operator == "#":
                entities = [entity for entity, value in zip(entities, values, strict=True) if abs(value) <= 1e-5]
            elif operator == "+":
                entities = [entity for entity, value in zip(entities, values, strict=True) if value >= 1 - 1e-5]
            else:
                entities = [entity for entity, value in zip(entities, values, strict=True) if value <= -1 + 1e-5]
    return entities


def _check_count(selection: Selection, count: int) -> None:
    expected = selection.expect
    if isinstance(expected, int):
        valid = count == expected
    elif expected == "one":
        valid = count == 1
    elif expected == "at_least_one":
        valid = count >= 1
    else:
        match = _RANGE.fullmatch(expected)
        valid = int(match[1]) <= count <= int(match[2])
    if not valid:
        raise CadError("SELECTION_COUNT", f"Se esperaban {expected} entidades y se encontraron {count}", hint="Consulta query topology y precisa los filtros; la geometría pudo cambiar")


def select(shape: Shape, kind: Literal["face", "edge"], selection: Selection, *, scope: str, origin: tuple[str, str] | None):
    if selection.refs is not None:
        roles = _roles(shape, kind, origin)
        chosen = []
        for name in selection.refs:
            match = _REF.fullmatch(name)
            if not match or match["kind"] != kind:
                raise CadError("INVALID_SELECTION", f"Referencia {kind} no válida: {name}")
            if origin is None or match["feature"] != origin[0] or name not in roles:
                raise CadError("REF_LOST", f"La referencia ya no corresponde a una {kind} única: {name}", hint="Usa query topology y selecciona una arista/cara vigente")
            chosen.append(roles[name])
    else:
        if selection.query.scope != scope or selection.query.kind != kind:
            raise CadError("INVALID_SELECTION", f"La query debe referirse al cuerpo {scope} y a {kind}s")
        chosen = _geometric_query(shape, kind, selection.query.where)
    _check_count(selection, len(chosen))
    return chosen


def topology(bodies: dict[str, Shape], source: dict[str, tuple[str, str]], *, body: str | None = None, kind: str = "all", limit: int = 100, cursor: int = 0) -> dict:
    if kind not in ("all", "face", "edge") or not 1 <= limit <= 100 or cursor < 0:
        raise CadError("INVALID_ARGUMENT", "Usa kind=all|face|edge, 1<=limit<=100 y cursor>=0")
    if body is not None and body not in bodies:
        raise CadError("UNKNOWN_BODY", f"Cuerpo desconocido: {body}")
    items: list[dict] = []
    for body_id, shape in bodies.items():
        if body is not None and body_id != body:
            continue
        for entity_kind in ("face", "edge"):
            if kind not in ("all", entity_kind):
                continue
            roles = _roles(shape, entity_kind, source.get(body_id))
            for entity in (shape.faces() if entity_kind == "face" else shape.edges()):
                # OCP puede devolver wrappers distintos para la misma topología: usar is_same.
                ref = next((name for name, candidate in roles.items() if entity.is_same(candidate)), None)
                record = {"body": body_id, "kind": entity_kind, "ref": ref, "geom_type": entity.geom_type.name,
                          "center_mm": [round(value, 6) for value in entity.center(CenterOf.MASS)]}
                if entity_kind == "face":
                    record.update({"area_mm2": round(entity.area, 6), "normal": [round(value, 6) for value in entity.normal_at()]})
                else:
                    record["length_mm"] = round(entity.length, 6)
                items.append(record)
    items.sort(key=lambda item: (item["body"], item["kind"], item["ref"] or "~", item["center_mm"], item.get("area_mm2", item.get("length_mm", 0))))
    page = items[cursor:cursor + limit]
    return {"total": len(items), "items": page, "next_cursor": cursor + limit if cursor + limit < len(items) else None}
