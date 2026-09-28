"""Adaptador mínimo del kernel: B-Rep exacto sin API de build123d expuesta a agentes."""

from collections.abc import Callable, Iterable, Mapping
from itertools import pairwise, product
from math import hypot
from pathlib import Path

from build123d import (
    Align,
    Axis,
    Box,
    Cylinder,
    Keep,
    Mesher,
    Plane,
    Polyline,
    Pos,
    Shape,
    Sketch,
    Transition,
    chamfer,
    export_gltf,
    export_step,
    export_stl,
    extrude,
    fillet,
    loft,
    mirror,
    offset,
    revolve,
    split,
    sweep,
)

from iacad.cache import GeometryCache
from iacad.commands import (
    BooleanArgs,
    BoxArgs,
    ChamferArgs,
    CylinderArgs,
    ExtrudeArgs,
    FilletArgs,
    HoleArgs,
    LoftArgs,
    MirrorArgs,
    PatternCircularArgs,
    PatternLinearArgs,
    RevolveArgs,
    ShellArgs,
    SplitArgs,
    SweepArgs,
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
    def _pattern_boolean(target: Shape, instances: Iterable[Shape], op: str) -> Shape:
        result = target
        for index, tool in enumerate(instances, start=1):
            try:
                updated = result - tool if op == "cut" else result + tool
            except Exception as exc:
                raise CadError("PATTERN_FAILED", f"Falló la instancia {index}", hint=str(exc)) from exc
            if not updated.is_valid or len(updated.solids()) != 1 or updated.volume <= 0:
                raise CadError("PATTERN_DISCONNECTED" if op == "join" else "PATTERN_FAILED",
                               f"La instancia {index} no produce un sólido único y válido",
                               hint="Acerca la herramienta al destino o ajusta el paso")
            change = (result.volume - updated.volume) if op == "cut" else (updated.volume - result.volume)
            if change <= max(1e-7, result.volume * 1e-9):
                raise CadError("PATTERN_NO_EFFECT", f"La instancia {index} no modifica el destino",
                               hint="Revisa la posición de la herramienta, dirección y paso")
            result = updated
        return result

    @staticmethod
    def _profile_solid(feature: Feature, args: ExtrudeArgs | RevolveArgs | LoftArgs | SweepArgs, build: Callable[[], Shape],
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
                    if args.op != "cut":
                        owners.pop(args.target, None)
                    if not args.keep_tools:
                        for tool in args.tools:
                            del bodies[tool]
                            del keys[tool]
                            owners.pop(tool, None)
                elif feature.type == "pattern_linear":
                    args = PatternLinearArgs.model_validate(feature.args)
                    if args.target not in bodies or args.source not in bodies:
                        raise CadError("UNKNOWN_BODY", "El patrón requiere dos cuerpos anteriores distintos",
                                       path="args.source")
                    spacing = positive(evaluator, args.spacing, "args.spacing")
                    norm = hypot(*args.direction)
                    direction = tuple(value / norm for value in args.direction)

                    def build_pattern(target=bodies[args.target], tool=bodies[args.source],
                                      count=args.count, step=spacing, vector=direction, op=args.op):
                        copies = (Pos(*(instance * step * coordinate for coordinate in vector)) * tool
                                  for instance in range(count))
                        return self._pattern_boolean(target, copies, op)

                    previous, source_key = keys[args.target], keys[args.source]
                    definition = {"type": "pattern_linear", "id": feature.id, "target_key": previous,
                                  "source_key": source_key, "op": args.op, "count": args.count,
                                  "spacing_mm": spacing, "direction": direction}
                    if cache is None or previous is None or source_key is None:
                        shape, key = build_pattern(), None
                    else:
                        shape, key = cache.get_or_build(definition, build_pattern)
                    bodies[args.target] = shape
                    keys[args.target] = key
                    owners.pop(args.target, None)
                    if not args.keep_tool:
                        del bodies[args.source]
                        del keys[args.source]
                        owners.pop(args.source, None)
                elif feature.type == "pattern_circular":
                    args = PatternCircularArgs.model_validate(feature.args)
                    if args.target not in bodies or args.source not in bodies:
                        raise CadError("UNKNOWN_BODY", "El patrón requiere dos cuerpos anteriores distintos",
                                       path="args.source")
                    angle = evaluator.angle(args.angle, path="args.angle")
                    if not 0 < angle <= 360:
                        raise CadError("INVALID_ANGLE", "El patrón requiere 0 < ángulo <= 360 deg", path="args.angle")
                    origin = tuple(evaluator.length(value, path=f"args.axis.origin[{i}]")
                                   for i, value in enumerate(args.axis.origin))
                    norm = hypot(*args.axis.dir)
                    direction = tuple(value / norm for value in args.axis.dir)
                    step = angle / (args.count if angle == 360 else args.count - 1)

                    def build_pattern(target=bodies[args.target], tool=bodies[args.source],
                                      count=args.count, increment=step, center=origin, vector=direction, op=args.op):
                        axis = Axis(center, vector)
                        copies = (tool.rotate(axis, instance * increment) for instance in range(count))
                        return self._pattern_boolean(target, copies, op)

                    previous, source_key = keys[args.target], keys[args.source]
                    definition = {"type": "pattern_circular", "id": feature.id, "target_key": previous,
                                  "source_key": source_key, "op": args.op, "count": args.count,
                                  "axis_origin_mm": origin, "axis_dir": direction, "angle_deg": angle}
                    if cache is None or previous is None or source_key is None:
                        shape, key = build_pattern(), None
                    else:
                        shape, key = cache.get_or_build(definition, build_pattern)
                    bodies[args.target] = shape
                    keys[args.target] = key
                    owners.pop(args.target, None)
                    if not args.keep_tool:
                        del bodies[args.source]
                        del keys[args.source]
                        owners.pop(args.source, None)
                elif feature.type == "mirror":
                    args = MirrorArgs.model_validate(feature.args)
                    if args.source not in bodies:
                        raise CadError("UNKNOWN_BODY", "No existe el cuerpo original", path="args.source")
                    if args.body in bodies:
                        raise CadError("DUPLICATE_ID", "El cuerpo reflejado ya existe", path="args.body")
                    origin = tuple(evaluator.length(value, path=f"args.plane.origin[{i}]")
                                   for i, value in enumerate(args.plane.origin))
                    norm = hypot(*args.plane.normal)
                    normal = tuple(value / norm for value in args.plane.normal)

                    def build_mirror(source=bodies[args.source], position=origin, direction=normal):
                        try:
                            return mirror(source, about=Plane(origin=position, z_dir=direction))
                        except Exception as exc:
                            raise CadError("MIRROR_FAILED", "El kernel no pudo reflejar el cuerpo",
                                           path="args.plane", hint=str(exc)) from exc

                    source_key = keys[args.source]
                    definition = {"type": "mirror", "id": feature.id, "source_key": source_key,
                                  "plane_origin_mm": origin, "plane_normal": normal}
                    if cache is None or source_key is None:
                        shape, key = build_mirror(), None
                    else:
                        shape, key = cache.get_or_build(definition, build_mirror)
                    bodies[args.body] = shape
                    keys[args.body] = key
                    # Los nombres topológicos del original no se transfieren a una copia reflejada.
                    owners.pop(args.body, None)
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
                    length = hypot(*args.axis.dir)
                    axis_dir = tuple(coord / length for coord in args.axis.dir)
                    plane_normal = tuple(PLANES[profile_key["plane"]].z_dir)
                    if abs(_dot3(axis_origin, plane_normal) - profile_key["offset_mm"]) > 1e-6 or abs(_dot3(axis_dir, plane_normal)) > 1e-7:
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
                elif feature.type == "loft":
                    args = LoftArgs.model_validate(feature.args)
                    sections = []
                    keys_for_sections = []
                    for sketch_id in args.sections:
                        if sketch_id not in sketches:
                            raise CadError("UNKNOWN_SKETCH", "El loft necesita croquis anteriores", path="args.sections")
                        profile, profile_key = sketches[sketch_id]
                        if profile is None or len(profile.faces()) != 1:
                            raise CadError("PROFILE_INVALID", "Cada sección debe contener una región cerrada",
                                           path="args.sections")
                        sections.append(profile)
                        keys_for_sections.append(profile_key)
                    planes = {key["plane"] for key in keys_for_sections}
                    if len(planes) != 1:
                        raise CadError("PROFILE_PLANES_MISMATCH", "Las secciones deben usar planos paralelos del mismo tipo",
                                       path="args.sections")
                    offsets = [key["offset_mm"] for key in keys_for_sections]
                    steps = [b - a for a, b in pairwise(offsets)]
                    if not (all(step > 1e-6 for step in steps) or all(step < -1e-6 for step in steps)):
                        raise CadError("SECTIONS_NOT_ORDERED", "Las secciones deben tener offsets distintos y ordenados",
                                       path="args.sections", hint="Ordénalas por offset a lo largo de la normal del plano")
                    holes = {len(key["entities"]) - 1 for key in keys_for_sections}
                    if len(holes) != 1:
                        raise CadError("PROFILE_HOLES_MISMATCH", "Todas las secciones deben tener igual número de huecos",
                                       path="args.sections")

                    def build_loft(profiles=tuple(sections), ruled=args.ruled):
                        try:
                            return loft(profiles, ruled=ruled)
                        except Exception as exc:
                            raise CadError("LOFT_FAILED", "El kernel no pudo unir las secciones",
                                           path="args.sections", hint=str(exc)) from exc

                    definition = {"type": "loft", "id": feature.id,
                                  "sections": [{"sketch": name, "profile": key}
                                               for name, key in zip(args.sections, keys_for_sections, strict=True)],
                                  "ruled": args.ruled}
                    shape = self._profile_solid(feature, args, build_loft, definition, bodies, keys, owners, cache)
                elif feature.type == "sweep":
                    args = SweepArgs.model_validate(feature.args)
                    if args.profile not in sketches:
                        raise CadError("UNKNOWN_SKETCH", "El barrido necesita un croquis anterior", path="args.profile")
                    profile, profile_key = sketches[args.profile]
                    if profile is None or len(profile.faces()) != 1:
                        raise CadError("PROFILE_INVALID", "El barrido necesita una región cerrada", path="args.profile")
                    points = [tuple(evaluator.length(value, path=f"args.path.points[{i}][{j}]")
                                    for j, value in enumerate(point)) for i, point in enumerate(args.path.points)]
                    segments = [tuple(b - a for a, b in zip(start, end, strict=True))
                                for start, end in pairwise(points)]
                    if any(hypot(*vector) <= 1e-6 for vector in segments):
                        raise CadError("PATH_INVALID", "La ruta contiene segmentos nulos o demasiado cortos",
                                       path="args.path.points")
                    normal = tuple(PLANES[profile_key["plane"]].z_dir)
                    if abs(_dot3(points[0], normal) - profile_key["offset_mm"]) > 1e-6:
                        raise CadError("PATH_NOT_ON_SKETCH", "La ruta debe comenzar en el plano del croquis",
                                       path="args.path.points[0]")
                    if abs(_dot3(segments[0], normal)) / hypot(*segments[0]) < 1 - 1e-6:
                        raise CadError("PATH_NOT_NORMAL", "El primer segmento debe seguir la normal del croquis",
                                       path="args.path.points[1]")

                    def build_sweep(source=profile, positions=tuple(points), transition=args.path.transition):
                        try:
                            path = Polyline(*positions)
                            return sweep(source, path=path, transition=Transition[transition.upper()])
                        except Exception as exc:
                            raise CadError("SWEEP_FAILED", "El kernel no pudo barrer el perfil",
                                           path="args.path.points", hint=str(exc)) from exc

                    definition = {"type": "sweep", "id": feature.id, "sketch": profile_key,
                                  "profile": args.profile, "points_mm": points,
                                  "transition": args.path.transition}
                    shape = self._profile_solid(feature, args, build_sweep, definition, bodies, keys, owners, cache)
                    if args.op != "new_body":
                        owners.pop(args.target, None)
                elif feature.type == "hole":
                    args = HoleArgs.model_validate(feature.args)
                    if args.target not in bodies:
                        raise CadError("UNKNOWN_BODY", "No existe el cuerpo a taladrar", path="args.target")
                    diameter = positive(evaluator, args.diameter, "args.diameter")
                    depth = positive(evaluator, args.depth, "args.depth") if args.mode == "blind" else None
                    origin = tuple(evaluator.length(value, path=f"args.axis.origin[{i}]")
                                   for i, value in enumerate(args.axis.origin))
                    norm = hypot(*args.axis.dir)
                    direction = tuple(value / norm for value in args.axis.dir)
                    source = bodies[args.target]
                    if depth is None:
                        bounds = source.bounding_box()
                        projections = [
                            _dot3(tuple(point[i] - origin[i] for i in range(3)), direction)
                            for point in product((bounds.min.X, bounds.max.X),
                                                 (bounds.min.Y, bounds.max.Y),
                                                 (bounds.min.Z, bounds.max.Z))
                        ]
                        margin = max(1e-3, (max(projections) - min(projections)) * 1e-6)
                        start = min(projections) - margin
                        length = max(projections) - min(projections) + 2 * margin
                    else:
                        start, length = 0.0, depth

                    def build_hole(base=source, position=origin, vector=direction,
                                   offset_mm=start, height=length, radius=diameter / 2):
                        try:
                            tool_origin = tuple(position[i] + offset_mm * vector[i] for i in range(3))
                            tool = Plane(origin=tool_origin, z_dir=vector) * Cylinder(
                                radius, height, align=(Align.CENTER, Align.CENTER, Align.MIN)
                            )
                            result = base - tool
                        except Exception as exc:
                            raise CadError("HOLE_FAILED", "El kernel no pudo taladrar el cuerpo",
                                           path="args.axis", hint=str(exc)) from exc
                        if not result.is_valid or len(result.solids()) != 1 or result.volume <= 0:
                            raise CadError("HOLE_FAILED", "El taladro no deja un sólido único y válido",
                                           path="args.diameter", hint="Reduce el diámetro o cambia el eje")
                        if base.volume - result.volume <= max(1e-7, base.volume * 1e-9):
                            raise CadError("HOLE_NO_EFFECT", "El taladro no intersecta el cuerpo",
                                           path="args.axis", hint="Comprueba el origen y la dirección")
                        return result

                    previous = keys[args.target]
                    definition = {"type": "hole", "id": feature.id, "target_key": previous,
                                  "diameter_mm": diameter, "axis_origin_mm": origin, "axis_dir": direction,
                                  "mode": args.mode, "depth_mm": depth, "start_mm": start, "length_mm": length}
                    if cache is None or previous is None:
                        shape, key = build_hole(), None
                    else:
                        shape, key = cache.get_or_build(definition, build_hole)
                    bodies[args.target] = shape
                    keys[args.target] = key
                    owners.pop(args.target, None)
                elif feature.type == "split":
                    args = SplitArgs.model_validate(feature.args)
                    if args.target not in bodies:
                        raise CadError("UNKNOWN_BODY", "No existe el cuerpo a cortar", path="args.target")
                    origin = tuple(evaluator.length(value, path=f"args.plane.origin[{i}]")
                                   for i, value in enumerate(args.plane.origin))
                    norm = hypot(*args.plane.normal)
                    direction = tuple(value / norm for value in args.plane.normal)
                    source = bodies[args.target]

                    def build_split(base=source, position=origin, vector=direction, keep=args.keep):
                        try:
                            result = split(base, bisect_by=Plane(origin=position, z_dir=vector),
                                           keep=Keep.TOP if keep == "positive" else Keep.BOTTOM)
                        except Exception as exc:
                            raise CadError("SPLIT_FAILED", "El kernel no pudo cortar el cuerpo",
                                           path="args.plane", hint=str(exc)) from exc
                        if result is None or len(result.solids()) == 0 or result.volume <= 0:
                            raise CadError("SPLIT_EMPTY", "El lado elegido no contiene un sólido",
                                           path="args.keep", hint="Mueve el plano o elige el lado contrario")
                        if not result.is_valid or len(result.solids()) != 1:
                            raise CadError("SPLIT_FAILED", "El corte no produce un sólido único y válido",
                                           path="args.plane", hint="Mueve el plano o cambia el cuerpo")
                        if base.volume - result.volume <= max(1e-7, base.volume * 1e-9):
                            raise CadError("SPLIT_NO_EFFECT", "El plano no recorta el cuerpo",
                                           path="args.plane", hint="Mueve el plano hacia el interior del sólido")
                        return result

                    previous = keys[args.target]
                    definition = {"type": "split", "id": feature.id, "target_key": previous,
                                  "plane_origin_mm": origin, "plane_normal": direction, "keep": args.keep}
                    if cache is None or previous is None:
                        shape, key = build_split(), None
                    else:
                        shape, key = cache.get_or_build(definition, build_split)
                    bodies[args.target] = shape
                    keys[args.target] = key
                    owners.pop(args.target, None)
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
                elif feature.type == "shell":
                    args = ShellArgs.model_validate(feature.args)
                    if args.target not in bodies:
                        raise CadError("UNKNOWN_BODY", "No existe el cuerpo a vaciar", path="args.target")
                    thickness = positive(evaluator, args.thickness, "args.thickness")
                    source = bodies[args.target]
                    selected = select(source, "face", args.remove_faces, scope=args.target,
                                      origin=owners.get(args.target))

                    def build_shell(base=source, openings=tuple(selected), size=thickness, direction=args.direction):
                        try:
                            result = offset(base, amount=-size if direction == "inward" else size,
                                            openings=list(openings))
                        except Exception as exc:
                            raise CadError("SHELL_FAILED", "El kernel no pudo vaciar el cuerpo",
                                           path="args.thickness", hint=str(exc)) from exc
                        if not result.is_valid or len(result.solids()) != 1 or result.volume <= 0:
                            raise CadError("SHELL_FAILED", "El espesor produjo una geometría inválida",
                                           path="args.thickness", hint="Reduce el espesor o cambia las caras abiertas")
                        if direction == "inward":
                            changed = base.volume - result.volume > max(1e-7, base.volume * 1e-9)
                        else:
                            old, new = base.bounding_box(), result.bounding_box()
                            changed = any(a - b > 1e-6 for a, b in zip(old.min, new.min, strict=True)) or any(
                                b - a > 1e-6 for a, b in zip(old.max, new.max, strict=True)
                            )
                        if not changed:
                            raise CadError("SHELL_FAILED", "El espesor no produjo un cascarón",
                                           path="args.thickness", hint="Reduce el espesor o cambia las caras abiertas")
                        return result

                    previous = keys[args.target]
                    definition = {"type": "shell", "id": feature.id, "target_key": previous,
                                  "remove_faces": args.remove_faces.model_dump(mode="json", exclude_none=True),
                                  "thickness_mm": thickness, "direction": args.direction}
                    if cache is None or previous is None:
                        shape, key = build_shell(), None
                    else:
                        shape, key = cache.get_or_build(definition, build_shell)
                    bodies[args.target] = shape
                    keys[args.target] = key
                    # El aro de una abertura puede ocupar el lugar de la antigua
                    # tapadera: bbox y normal NO demuestran su procedencia.
                    owners.pop(args.target, None)
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
