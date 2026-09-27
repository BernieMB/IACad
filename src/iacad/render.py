"""Captura técnica de la malla calculada a partir del B-Rep; sin interfaz gráfica."""

import math
from pathlib import Path

from build123d import Shape
from PIL import Image, ImageDraw, ImageFont

from iacad.errors import CadError

VIEWS = {
    "front": (0, -1, 0),
    "top": (0, 0, 1),
    "right": (1, 0, 0),
    "iso": (1, -1, 1),
}
MAX_TRIANGLES = 100_000


def _unit(v):
    length = math.sqrt(sum(x * x for x in v))
    return tuple(x / length for x in v)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _axes(name: str):
    toward_camera = _unit(VIEWS[name])
    approximate_up = (0, 1, 0) if name == "top" else (0, 0, 1)
    screen_x = _unit(_cross(approximate_up, toward_camera))
    screen_y = _cross(toward_camera, screen_x)
    return screen_x, screen_y, toward_camera


def _tile(draw: ImageDraw.ImageDraw, shape: Shape, name: str, region: tuple[int, int, int, int]):
    left, top, width, height = region
    vertices, triangles = shape.tessellate(0.12)
    if len(triangles) > MAX_TRIANGLES:
        raise CadError("RENDER_TOO_COMPLEX", "Malla demasiado densa para previsualización", hint="Usa export glb para abrirla en un visor")
    sx, sy, forward = _axes(name)
    transformed = [(_dot(tuple(v), sx), _dot(tuple(v), sy), _dot(tuple(v), forward)) for v in vertices]
    if not transformed:
        raise CadError("INVALID_GEOMETRY", "Pieza sin triángulos para renderizar")
    mins = [min(v[i] for v in transformed) for i in (0, 1)]
    maxs = [max(v[i] for v in transformed) for i in (0, 1)]
    scale = min((width - 44) / max(maxs[0] - mins[0], 0.001),
                (height - 54) / max(maxs[1] - mins[1], 0.001))
    center = [(lo + hi) / 2 for lo, hi in zip(mins, maxs, strict=True)]

    def point(index):
        x, y, _ = transformed[index]
        return (left + width / 2 + (x - center[0]) * scale,
                top + height / 2 - (y - center[1]) * scale)

    shaded = []
    for indices in triangles:
        a, b, c = (tuple(vertices[i]) for i in indices)
        normal = _cross(tuple(b[j] - a[j] for j in range(3)), tuple(c[j] - a[j] for j in range(3)))
        length = math.sqrt(_dot(normal, normal))
        if length <= 1e-12:
            continue
        normal = tuple(x / length for x in normal)
        if _dot(normal, forward) <= 1e-6:
            continue
        depth = sum(transformed[i][2] for i in indices) / 3
        light = _unit((0.5, -0.4, 1.0))
        brightness = max(0.25, min(1.0, 0.55 + 0.45 * _dot(normal, light)))
        color = (int(99 * brightness), int(169 * brightness), int(208 * brightness))
        shaded.append((depth, [point(i) for i in indices], color))
    for _, polygon, color in sorted(shaded, key=lambda row: row[0]):
        draw.polygon(polygon, fill=color)
    draw.text((left + 12, top + 9), name.upper(), fill=(220, 228, 242), font=ImageFont.load_default())


def render(shape: Shape, path: Path, views: str = "iso", size: int = 768) -> dict:
    """Renderiza un cuerpo como PNG sin Blender ni contexto GPU."""

    if views not in (*VIEWS, "four") or not 256 <= size <= 1024:
        raise CadError("INVALID_ARGUMENT", "Usa views=iso|front|top|right|four y size=256..1024")
    image = Image.new("RGB", (size, size), (24, 30, 41))
    draw = ImageDraw.Draw(image)
    if views == "four":
        half = size // 2
        for index, view in enumerate(("iso", "front", "top", "right")):
            _tile(draw, shape, view, ((index % 2) * half, (index // 2) * half, half, half))
    else:
        _tile(draw, shape, views, (0, 0, size, size))
    image.save(path, format="PNG")
    return {"views": views, "resolution": [size, size]}
