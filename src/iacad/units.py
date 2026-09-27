"""Evaluación limitada de cantidades y parámetros, sin eval() de Python."""

import ast
import math
import re

import pint

from iacad.errors import CadError
from iacad.model import Document, Quantity

_ureg = pint.UnitRegistry()
_UNIT_LITERAL = re.compile(
    r"(?<![\w.])(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"\s*(?P<unit>mm\^3|cm\^3|m\^3|mm|cm|inch|in|ft|m|deg|rad)\b"
)
_UNITS = {"mm": "millimeter", "cm": "centimeter", "m": "meter", "in": "inch", "inch": "inch", "ft": "foot", "deg": "degree", "rad": "radian", "mm^3": "millimeter ** 3", "cm^3": "centimeter ** 3", "m^3": "meter ** 3"}
_FUNCTIONS = {"abs": abs, "min": min, "max": max, "sqrt": lambda x: x ** 0.5}


class QuantityEvaluator:
    def __init__(self, document: Document):
        self.document = document
        self.parameters = {p.name: p for p in document.parameters}

    def length(self, value: Quantity, *, path: str = "") -> float:
        quantity = self._quantity(value, path=path)
        try:
            if quantity.units == _ureg.dimensionless:
                quantity *= _ureg(_UNITS[self.document.units.length])
            result = quantity.to("millimeter").magnitude
        except (pint.DimensionalityError, pint.UndefinedUnitError) as exc:
            raise CadError("UNIT_MISMATCH", f"Se esperaba longitud: {value}", path=path) from exc
        if not math.isfinite(result):
            raise CadError("INVALID_NUMBER", "Se requiere una longitud finita", path=path)
        return float(result)

    def volume(self, value: Quantity) -> float:
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            return float(value)  # Los checks expresan números de volumen en mm³.
        quantity = self._quantity(value)
        try:
            if quantity.units == _ureg.dimensionless:
                return float(quantity.magnitude)
            return float(quantity.to("millimeter ** 3").magnitude)
        except pint.DimensionalityError as exc:
            raise CadError("UNIT_MISMATCH", "El check de volumen requiere mm^3") from exc

    def angle(self, value: Quantity, *, path: str = "") -> float:
        quantity = self._quantity(value, path=path)
        try:
            if quantity.units == _ureg.dimensionless:
                quantity *= _ureg(_UNITS[self.document.units.angle])
            if quantity.units not in (_ureg.degree, _ureg.radian):
                raise CadError("UNIT_MISMATCH", f"Se esperaba un ángulo de primer grado: {value}", path=path)
            result = quantity.to("degree").magnitude
        except (pint.DimensionalityError, pint.UndefinedUnitError) as exc:
            raise CadError("UNIT_MISMATCH", f"Se esperaba ángulo: {value}", path=path) from exc
        if not math.isfinite(result):
            raise CadError("INVALID_NUMBER", "Se requiere un ángulo finito", path=path)
        return float(result)

    def validate_parameters(self) -> None:
        for name, parameter in self.parameters.items():
            resolve = self.angle if parameter.kind == "angle" else self.length
            value = resolve(parameter.value, path=f"parameters.{name}")
            if parameter.min is not None and value < resolve(parameter.min):
                raise CadError("PARAM_OUT_OF_RANGE", f"{name} menor que el mínimo", path=name)
            if parameter.max is not None and value > resolve(parameter.max):
                raise CadError("PARAM_OUT_OF_RANGE", f"{name} mayor que el máximo", path=name)

    def resolved(self) -> dict[str, float]:
        self.validate_parameters()
        return {name: self.length(p.value) for name, p in self.parameters.items() if p.kind == "length"}

    def resolved_angles(self) -> dict[str, float]:
        self.validate_parameters()
        return {name: self.angle(p.value) for name, p in self.parameters.items() if p.kind == "angle"}

    def _quantity(self, value: Quantity, *, path: str = "", stack: tuple[str, ...] = ()):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise CadError("INVALID_QUANTITY", "La cantidad debe ser número o expresión", path=path)
        if isinstance(value, (int, float)):
            return _ureg.Quantity(value)
        source = _UNIT_LITERAL.sub(lambda m: f"Q({m['number']},'{_UNITS[m['unit']]}')", value).replace("^", "**")
        try:
            tree = ast.parse(source, mode="eval")
            return self._eval(tree.body, stack)
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError, pint.PintError) as exc:
            raise CadError("INVALID_EXPRESSION", f"Expresión inválida: {value}", path=path, hint=str(exc)) from exc

    def _eval(self, node: ast.AST, stack: tuple[str, ...]):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return _ureg.Quantity(node.value)
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return _ureg.Quantity(math.pi)
            parameter = self.parameters.get(node.id)
            if parameter is None:
                raise CadError("UNKNOWN_PARAMETER", f"Parámetro desconocido: {node.id}")
            if node.id in stack:
                raise CadError("PARAM_CYCLE", f"Dependencia circular: {' → '.join((*stack, node.id))}")
            resolved = self._quantity(parameter.value, stack=(*stack, node.id))
            if resolved.units == _ureg.dimensionless:
                unit = self.document.units.angle if parameter.kind == "angle" else self.document.units.length
                resolved *= _ureg(_UNITS[unit])
            return resolved
        if isinstance(node, ast.UnaryOp) and type(node.op) in (ast.USub, ast.UAdd):
            value = self._eval(node.operand, stack)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow):
            left, right = self._eval(node.left, stack), self._eval(node.right, stack)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if right.units != _ureg.dimensionless:
                raise CadError("UNIT_MISMATCH", "El exponente debe ser adimensional")
            return left ** right.magnitude
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            if node.func.id == "Q" and len(node.args) == 2:
                num, unit = node.args
                if isinstance(num, ast.Constant) and isinstance(unit, ast.Constant):
                    return _ureg.Quantity(num.value, unit.value)
            if node.func.id in _FUNCTIONS and len(node.args) in (1, 2):
                return _FUNCTIONS[node.func.id](*(self._eval(a, stack) for a in node.args))
        raise CadError("UNSAFE_EXPRESSION", "Expresión no permitida", hint="Solo operaciones aritméticas, parámetros y unidades")
