"""Ejemplo de plugin instalable: entry point `iacad.plugins = esfera = plugin_sphere:setup`."""

from build123d import Align, Pos, Sphere
from pydantic import Field

from iacad.model import ID_PATTERN, Body, Feature, PartDocument, Quantity, StrictModel


class SphereArgs(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    body: str = Field(pattern=ID_PATTERN)
    radius: Quantity


def setup(register, register_feature):
    @register("demo.sphere", SphereArgs, "Esfera de demostración.", {"id": "bola", "body": "principal", "radius": "5 mm"})
    def apply(document: PartDocument, args: SphereArgs) -> str:
        document.features.append(Feature(id=args.id, type="demo:sphere", args=args.model_dump()))
        document.bodies.append(Body(id=args.body))
        return args.id

    def construct(feature, bodies, evaluator):
        args = SphereArgs.model_validate(feature.args)
        shape = Pos(0, 0, 0) * Sphere(evaluator.length(args.radius), align=(Align.CENTER, Align.CENTER, Align.CENTER))
        bodies[args.body] = shape
        return shape

    register_feature("demo:sphere", construct)
