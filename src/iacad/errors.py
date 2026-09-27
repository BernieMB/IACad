"""Errores recuperables, legibles por humanos y agentes."""


class CadError(Exception):
    def __init__(self, code: str, message: str, *, path: str = "", hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.hint = hint

    def as_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "path": self.path, "hint": self.hint}


def failure(exc: CadError) -> dict:
    return {"ok": False, "error": exc.as_dict()}
