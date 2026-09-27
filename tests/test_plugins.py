"""Un plugin añade un comando y un sólido sin modificar el bus ni el kernel."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from iacad.commands import COMMANDS, register
from iacad.kernel import FEATURE_HANDLERS, register_feature
from iacad.service import CADService


def test_installed_plugin_extension_points(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "plugin_sphere.py"
    spec = spec_from_file_location("plugin_sphere", source)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.setup(register, register_feature)
        service = CADService(root=tmp_path)
        service.new("parts/esfera.iacad", "Esfera")
        answer = service.execute("parts/esfera.iacad", [
            {"cmd": "demo.sphere", "args": {"id": "bola", "body": "principal", "radius": "5 mm"}},
        ])
        assert answer["summary"]["bodies"] == 1
        assert answer["summary"]["volume_mm3"] > 500
        assert service.help("demo.sphere")["example"]["args"]["id"] == "bola"
    finally:
        COMMANDS.pop("demo.sphere", None)
        FEATURE_HANDLERS.pop("demo:sphere", None)
