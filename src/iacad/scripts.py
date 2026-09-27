"""IACad Script: un comando por línea; sintaxis key=value o JSONL."""

import json
import re
import shlex

from iacad.errors import CadError


def parse_script(text: str) -> list[dict]:
    commands: list[dict] = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            if line.startswith("{"):
                commands.append(json.loads(line))
                continue
            tokens = shlex.split(line, comments=True, posix=True)
            if not tokens:
                continue
            name = tokens[0]
            args: dict = {}
            for token in tokens[1:]:
                if "=" not in token:
                    raise ValueError(f"Se esperaba clave=valor: {token}")
                key, value = token.split("=", 1)
                if not key or key in args:
                    raise ValueError(f"Clave vacía o repetida: {key}")
                try:
                    args[key] = json.loads(value)
                except json.JSONDecodeError:
                    args[key] = value
            if name == "param.set" and "name" not in args:
                # Atajo legible: param.set espesor=5mm ancho=50mm
                for key, value in args.items():
                    commands.append({"cmd": "param.set", "args": {"name": key, "value": value}})
            else:
                if name == "feature.boolean" and isinstance(args.get("tools"), str):
                    args["tools"] = args["tools"].split(",")
                if name == "feature.extrude" and "distance" in args and not isinstance(args.get("extent"), dict):
                    args["extent"] = {"type": args.pop("extent", "distance"), "distance": args.pop("distance")}
                if name in ("feature.fillet", "feature.chamfer") and isinstance(args.get("edges"), str) and "expect" in args:
                    selection = args.pop("edges")
                    expect = args.pop("expect")
                    if selection.startswith("@"):
                        args["edges"] = {"refs": [selection], "expect": expect}
                    else:
                        match = re.fullmatch(r"\?([a-z][a-z0-9_]*)/edges\[(.+)\]", selection)
                        if match:
                            args["edges"] = {"query": {"scope": match[1], "kind": "edge", "where": match[2]}, "expect": expect}
                        else:
                            raise ValueError(f"Selección de arista no válida: {selection}")
                commands.append({"cmd": name, "args": args})
        except (ValueError, json.JSONDecodeError) as exc:
            raise CadError("SCRIPT_SYNTAX", f"Línea {number} inválida", path=f"line:{number}", hint=str(exc)) from exc
    if not commands:
        raise CadError("EMPTY_SCRIPT", "El script no contiene comandos")
    return commands
