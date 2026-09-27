"""Adaptador mínimo del kernel: B-Rep exacto sin API de build123d expuesta a agentes."""

from collections.abc import Callable, Mapping
from math import sqrt
from pathlib import Path

from build123d import (
    Align,
    Axis,
    Box,
    Cylinder,
    Mesher,
    Pos,
    Shape,
    Sketch,
    chamfer,
    export_gltf,
    export_step,
    export_stl,
    extrude,
    fillet,
    revolve,
)

from iacad.cache import GeometryCache
from iacad.commands import (
    BooleanArgs,
    BoxArgs,
    ChamferArgs,
    CylinderArgs,
    ExtrudeArgs,
    FilletArgs,
    RevolveArgs,
)
from iacad.errors import CadError
from iacad.model import Feature, PartDocument
from iacad.naming import select
from iacad.sketch import PLANES, SketchDefinition, resolve
from iacad.units import QuantityEvaluator


def positive(evaluator: QuantityEvaluator, value: str | float, path: str) -> float:
    number = evaluator.length(value, path=path)
    if number <= 0:
        raise CadError("INVALID_DIMENSION", "La dimensión debe ser mayor que cero", path=path)
    return number


def coordinates(evaluator: QuantityEvaluator, origin: list[str | float]) -> tuple[float, float, float]:
    return tuple(evaluator.length(n, path=f"args.origin[{i}]") for i, n in enumerate(origin))


def _dot3(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


FEATURE_HANDLERS: dict[str, Callable[[Feature, dict[str, Shape], QuantityEvaluator], Shape]] = {}


def register_feature(name: str, handler: Callable[[Feature, dict[str, Shape], QuantityEvaluator], Shape]) -> None:
    """Los plugins registran nuevos tipos de geometría sin editar KernelAdapter."""

    if ":" not in name or name in FEATURE_HANDLERS or name in ("box", "cylinder", "boolean"):
        raise ValueError(f"Feature de plugin no válida o duplicada: {name}")
    FEATURE_HANDLERS[name] = handler


class KernelAdapter:
    """Punto de reemplazo de build123d; se mantiene fuera de documento/comandos."""

    @staticmethod
    def _profile_solid(feature: Feature, args: ExtrudeArgs | RevolveArgs, build: Callable[[], Shape],
                       definition: dict, bodies: dict[str, Shape], keys: dict[str, str | None],
                       owners: dict[str, tuple[str, str]], cache: GeometryCache | None) -> Shape:
        if args.op == "new_body":
            if args.body in bodies:
                raise CadError("DUPLICATE_ID", "El cuerpo de salida ya existe", path="args.body")
            shape, key = (build(), None) if cache is None else cache.get_or_build(definition, build)
            bodies[args.body] = shape
            keys[args.body] = key
            owners[args.body] = (feature.id, feature.type)
            return shape
        if args.target not in bodies:
            raise CadError("UNKNOWN_BODY", "No existe el cuerpo destino", path="args.target")

        def combine(target=bodies[args.target], op=args.op, make_tool=build):
            tool = make_tool()
            if op == "join":
                return target + tool
            if op == "cut":
                return target - tool
            return target & tool

        prior = keys[args.target]
        if cache is None or prior is None:
            shape, key = combine(), None
        else:
            shape, key = cache.get_or_build({**definition, "op": args.op, "target_key": prior}, combine)
        bodies[args.target] = shape
        keys[args.target] = key
        return shape

    def regenerate(self, document: PartDocument, cache: GeometryCache | None = None) -> dict[str, Shape]:
        evaluator = QuantityEvaluator(document)
        evaluator.validate_parameters()
        bodies: dict[str, Shape] = {}
        keys: dict[str, str | None] = {}
        owners: dict[str, tuple[str, str]] = {}
        sketches: dict[str, tuple[Sketch | None, dict]] = {}
        for index, feature in enumerate(document.features):
            if feature.suppressed:
                raise CadError("FEATURE_UNSUPPORTED", "Supresión de features aún no disponible", path=f"features[{index}]")
            try:
                if feature.type == "sketch":
                    definition = SketchDefinition.model_validate(feature.args)
                    sketches[feature.id] = resolve(definition, evaluator)
                    continue
                if feature.type == "box":
                    args = BoxArgs.model_validate(feature.args)
                    sizes = [
                        positive(evaluator, args.length, "args.length"),
                        positive(evaluator, args.width, "args.width"),
                        positive(evaluator, args.height, "args.height"),
                    ]
                    origin = coordinates(evaluator, args.origin)
                    if args.body in bodies:
                        raise CadError("DUPLICATE_ID", f"Cuerpo ya existente: {args.body}")
                    def build_box(position=origin, dimensions=tuple(sizes)):
                        return Pos(*position) * Box(*dimensions, align=(Align.MIN, Align.MIN, Align.MIN))

                    if cache is None:
                        shape, key = build_box(), None
                    else:
                        shape, key = cache.get_or_build(
                            {"type": "box", "id": feature.id, "size_mm": sizes, "origin_mm": origin},
                            build_box,
                        )
                    bodies[args.body] = shape
                    keys[args.body] = key
                    owners[args.body] = (feature.id, feature.type)
                elif feature.type == "cylinder":
                    args = CylinderArgs.model_validate(feature.args)
                    radius = positive(evaluator, args.radius, "args.radius")
                    height = positive(evaluator, args.height, "args.height")
                    origin = coordinates(evaluator, args.origin)
                    if args.body in bodies:
                        raise CadError("DUPLICATE_ID", f"Cuerpo ya existente: {args.body}")
                    def build_cylinder(position=origin, r=radius, length=height):
                        return Pos(*position) * Cylinder(
                            r, length, align=(Align.CENTER, Align.CENTER, Align.MIN)
                        )

                    if cache is None:
                        shape, key = build_cylinder(), None
                    else:
                        shape, key = cache.get_or_build(
                            {"type": "cylinder", "id": feature.id, "radius_mm": radius,
                             "height_mm": height, "origin_mm": origin},
                            build_cylinder,
                        )
                    bodies[args.body] = shape
                    keys[args.body] = key
                    owners[args.body] = (feature.id, feature.type)
                elif feature.type == "boolean":
                    args = BooleanArgs.model_validate(feature.args)
                    if args.target not in bodies or any(tool not in bodies for tool in args.tools):
                        raise CadError("UNKNOWN_BODY", "Cuerpo booleano desconocido", path=f"features[{index}]")
                    for tool in args.tools:
                        if tool == args.target:
                            raise CadError("INVALID_ARGUMENT", "Un cuerpo no puede ser su propia herramienta")
                    def build_boolean(target=bodies[args.target], tools=tuple(bodies[t] for t in args.tools), op=args.op):
                        result = target
                        for tool in tools:
                            if op == "cut":
                                result = result - tool
                            elif op == "union":
                                result = result + tool
                            else:
                                result = result & tool
                        return result

                    inputs = [keys[args.target], *(keys[tool] for tool in args.tools)]
                    if cache is None or any(key is None for key in inputs):
                        shape, key = build_boolean(), None
                    else:
                        shape, key = cache.get_or_build(
                            {"type": "boolean", "id": feature.id, "op": args.op,
                             "inputs": inputs},
                            build_boolean,
                        )
                    bodies[args.target] = shape
                    keys[args.target] = key
                    if not args.keep_tools:
                        for tool in args.tools:
                            del bodies[tool]
                            del keys[tool]
                            owners.pop(tool, None)
                elif feature.type == "extrude":
                    args = ExtrudeArgs.model_validate(feature.args)
                    if args.profile not in sketches:
                        raise CadError("UNKNOWN_SKETCH", "La extrusión necesita un croquis anterior", path="args.profile")
                    profile, profile_key = sketches[args.profile]
                    if profile is None:
                        raise CadError("PROFILE_INVALID", "El croquis no contiene un contorno cerrado", path="args.profile")
                    distance = positive(evaluator, args.extent.distance, "args.extent.distance")
                    plane = PLANES[profile_key["plane"]]

                    def build_extrude(source=profile, size=distance, extent=args.extent.type, direction=args.direction, normal=tuple(plane.z_dir)):
                        if extent == "symmetric":
                            source = Pos(*(axis * -size / 2 for axis in normal)) * source
                        return extrude(source, amount=-size if direction == "reverse" else size)

                    definition = {
                        "type": "extrude", "id": feature.id, "profile": args.profile,
                        "sketch": profile_key, "distance_mm": distance,
                        "extent": args.extent.type, "direction": args.direction,
                    }
                    shape = self._profile_solid(feature, args, build_extrude, definition, bodies, keys, owners, cache)
                elif feature.type == "revolve":
                    args = RevolveArgs.model_validate(feature.args)
                    if args.profile not in sketches:
                        raise CadError("UNKNOWN_SKETCH", "La revolución necesita un croquis anterior", path="args.profile")
                    profile, profile_key = sketches[args.profile]
                    if profile is None:
                        raise CadError("PROFILE_INVALID", "El croquis no contiene un contorno cerrado", path="args.profile")
                    angle = evaluator.angle(args.angle, path="args.angle")
                    if not 0 < angle <= 360:
                        raise CadError("INVALID_ANGLE", "La revolución requiere 0 < ángulo <= 360 deg", path="args.angle")
                    axis_origin = tuple(evaluator.length(coord, path="args.axis.origin") for coord in args.axis.origin)
                    length = sqrt(sum(coord * coord for coord in args.axis.dir))
                    axis_dir = tuple(coord / length for coord in args.axis.dir)
                    plane_normal = tuple(PLANES[profile_key["plane"]].z_dir)
                    if abs(_dot3(axis_origin, plane_normal)) > 1e-6 or abs(_dot3(axis_dir, plane_normal)) > 1e-7:
                        raise CadError("AXIS_NOT_IN_SKETCH_PLANE", "El eje de revolución debe estar en el plano del croquis", path="args.axis")
                    side = (axis_dir[1] * plane_normal[2] - axis_dir[2] * plane_normal[1],
                            axis_dir[2] * plane_normal[0] - axis_dir[0] * plane_normal[2],
                            axis_dir[0] * plane_normal[1] - axis_dir[1] * plane_normal[0])
                    # Los círculos pueden tener un único vértice en su costura; muestrear
                    # sus aristas evita aceptar un perfil que cruza el eje entre vértices.
                    offsets = [
                        _dot3(tuple(value - axis_origin[i] for i, value in enumerate(edge.position_at(t / 8))), side)
                        for edge in profile.edges() for t in range(9)
                    ]
                    if min(offsets) < -1e-6 and max(offsets) > 1e-6:
                        raise CadError("PROFILE_CROSSES_AXIS", "El perfil cruza ambos lados del eje y podría autointersecarse", path="args.profile")

                    def build_revolve(source=profile, origin=axis_origin, direction=axis_dir, arc=angle):
                        return revolve(source, axis=Axis(origin, direction), revolution_arc=arc)

                    definition = {"type": "revolve", "id": feature.id, "profile": args.profile,
                                  "sketch": profile_key, "axis_origin_mm": axis_origin,
                                  "axis_dir": axis_dir, "angle_deg": angle}
                    shape = self._profile_solid(feature, args, build_revolve, definition, bodies, keys, owners, cache)
                elif feature.type in ("fillet", "chamfer"):
                    args = (FilletArgs if feature.type == "fillet" else ChamferArgs).model_validate(feature.args)
                    if args.target not in bodies:
                        raise CadError("UNKNOWN_BODY", "No existe el cuerpo de la operación de acabado", path="args.target")
                    amount = positive(evaluator, args.radius if feature.type == "fillet" else args.distance,
                                      "args.radius" if feature.type == "fillet" else "args.distance")
                    selected = select(bodies[args.target], "edge", args.edges, scope=args.target,
                                      origin=owners.get(args.target))

                    def build_dressup(edges=tuple(selected), size=amount, mode=feature.type):
                        try:
                            return fillet(edges, size) if mode == "fillet" else chamfer(edges, size)
                        except Exception as exc:
                            raise CadError("FILLET_FAILED" if mode == "fillet" else "CHAMFER_FAILED",
                                           f"No se pudo aplicar {mode}", hint=str(exc)) from exc

                    previous = keys[args.target]
                    definition = {"type": feature.type, "id": feature.id, "target_key": previous,
                                  "edges": args.edges.model_dump(mode="json", exclude_none=True), "size_mm": amount}
                    if cache is None or previous is None:
                        shape, key = build_dressup(), None
                    else:
                        shape, key = cache.get_or_build(definition, build_dressup)
                    bodies[args.target] = shape
                    keys[args.target] = key
                elif feature.type in FEATURE_HANDLERS:
                    shape = FEATURE_HANDLERS[feature.type](feature, bodies, evaluator)
                    # Un plugin puede modificar cualquier cuerpo: evitar resultados obsoletos.
                    keys = dict.fromkeys(bodies)
                    owners.clear()
                else:
                    raise CadError("FEATURE_UNSUPPORTED", f"Feature no implementada: {feature.type}", path=f"features[{index}].type")
                if not shape.is_valid or len(shape.solids()) != 1 or shape.volume <= 0:
                    raise CadError("INVALID_GEOMETRY", f"La feature {feature.id} no produjo un sólido válido", path=f"features[{index}]", hint="Comprueba posiciones y dimensiones de la operación")
            except CadError:
                raise
            except Exception as exc:
                raise CadError("GEOMETRY_FAILED", f"Falló la feature {feature.id}", path=f"features[{index}]", hint=str(exc)) from exc
        if set(bodies) != {b.id for b in document.bodies}:
            raise CadError("BODY_MISMATCH", "La lista de cuerpos no coincide con el historial de features", path="bodies")
        return bodies

    def summary(self, bodies: Mapping[str, Shape]) -> dict:
        return {
            "bodies": len(bodies),
            "valid": all(shape.is_valid for shape in bodies.values()),
            "volume_mm3": round(sum(shape.volume for shape in bodies.values()), 6),
            "bounds_mm": {
                name: {"min": [round(n, 6) for n in shape.bounding_box().min],
                       "max": [round(n, 6) for n in shape.bounding_box().max]}
                for name, shape in bodies.items()
            },
        }

    def export(self, bodies: Mapping[str, Shape], fmt: str, path: Path) -> None:
        if len(bodies) != 1:
            raise CadError("EXPORT_REQUIRES_SINGLE_BODY", "La exportación del MVP requiere exactamente un cuerpo", hint="Une los cuerpos primero con feature.boolean op=union")
        shape = next(iter(bodies.values()))
        try:
            if fmt == "step":
                ok = export_step(shape, path, timestamp="2000-01-01T00:00:00")
            elif fmt == "stl":
                ok = export_stl(shape, path)
            elif fmt == "glb":
                ok = export_gltf(shape, path, binary=True)
            elif fmt == "3mf":
                mesher = Mesher()
                mesher.add_shape(shape)
                mesher.write(path)
                ok = path.is_file() and path.stat().st_size > 0
            else:
                raise CadError("FORMAT_UNSUPPORTED", f"Formato no implementado: {fmt}")
            if not ok:
                raise CadError("EXPORT_FAILED", "El kernel no pudo exportar el sólido", path=str(path))
        except CadError:
            raise
        except Exception as exc:
            raise CadError("EXPORT_FAILED", "Error del kernel al exportar", path=str(path), hint=str(exc)) from exc
