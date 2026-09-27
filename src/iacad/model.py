"""Fuente de verdad del MVP: documentos CAD de pieza (JSON validable)."""

import secrets
import time
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ulid() -> str:
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    result = ""
    for _ in range(26):
        value, digit = divmod(value, 32)
        result = alphabet[digit] + result
    return result


Id = str
Quantity = float | str
ID_PATTERN = r"^[a-z][a-z0-9_]{0,62}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Units(StrictModel):
    length: Literal["mm", "cm", "m", "in", "ft"] = "mm"
    angle: Literal["deg", "rad"] = "deg"
    mass: Literal["g", "kg", "lb"] = "g"


class Metadata(StrictModel):
    description: str = ""
    author: str = ""
    created: str = Field(default_factory=now)
    modified: str = Field(default_factory=now)
    tool_version: str = "iacad 0.1.0"
    tags: list[str] = Field(default_factory=list)


class Parameter(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: Quantity
    kind: Literal["length", "angle"] = "length"
    min: Quantity | None = None
    max: Quantity | None = None
    group: str = ""
    description: str = ""


class Body(StrictModel):
    id: Id = Field(pattern=ID_PATTERN)
    material: str | None = None
    appearance: str | None = None
    export: bool = True


class Feature(StrictModel):
    id: Id = Field(pattern=ID_PATTERN)
    type: str
    args: dict
    name: str = ""
    notes: str = ""
    suppressed: bool = False
    tags: list[str] = Field(default_factory=list)
    extensions: dict = Field(default_factory=dict)


class PartDocument(StrictModel):
    format: Literal["iacad"] = "iacad"
    format_version: Literal["1.0"] = "1.0"
    kind: Literal["part"] = "part"
    uid: str = Field(default_factory=ulid, pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")
    name: str = Field(min_length=1, max_length=200)
    revision: int = Field(default=0, ge=0)
    units: Units = Field(default_factory=Units)
    metadata: Metadata = Field(default_factory=Metadata)
    parameters: list[Parameter] = Field(default_factory=list)
    properties: dict = Field(default_factory=dict)
    bodies: list[Body] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    checks: list[dict] = Field(default_factory=list)
    configurations: list[dict] = Field(default_factory=list)
    extensions: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_ids(self) -> "PartDocument":
        for label, items in (("feature", self.features), ("body", self.bodies)):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Los IDs de {label} deben ser únicos")
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("Los parámetros deben tener nombres únicos")
        return self


class Requirement(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,62}$")
    text: str = Field(min_length=1)
    verified_by: list[str] = Field(default_factory=list)


class Brief(StrictModel):
    summary: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class DocumentRef(StrictModel):
    path: str = Field(min_length=1)
    kind: Literal["part"] = "part"
    uid: str = Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")


class ProjectDocument(StrictModel):
    format: Literal["iacad"] = "iacad"
    format_version: Literal["1.0"] = "1.0"
    kind: Literal["project"] = "project"
    uid: str = Field(default_factory=ulid, pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$")
    name: str = Field(min_length=1, max_length=200)
    revision: int = Field(default=0, ge=0)
    units: Units = Field(default_factory=Units)
    metadata: Metadata = Field(default_factory=Metadata)
    brief: Brief = Field(default_factory=Brief)
    parameters: list[Parameter] = Field(default_factory=list)
    documents: list[DocumentRef] = Field(default_factory=list)
    libraries: list[str] = Field(default_factory=list)
    settings: dict = Field(default_factory=dict)
    extensions: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_refs(self) -> "ProjectDocument":
        for label, ids in (
            ("documentos", [item.path for item in self.documents]),
            ("requisitos", [item.id for item in self.brief.requirements]),
            ("parámetros", [item.name for item in self.parameters]),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"Los {label} deben ser únicos")
        return self


Document = PartDocument | ProjectDocument
DOCUMENT_ADAPTER: TypeAdapter[Document] = TypeAdapter(Document)
