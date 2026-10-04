from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Option(_Strict):
    value: str
    synonyms: list[str] = []


class _FieldBase(_Strict):
    key: str = Field(pattern=KEY_PATTERN)
    label: str | None = None
    hint: str | None = None
    required: bool = False
    source: Literal["dicom"] | None = None


class TextField(_FieldBase):
    type: Literal["text"]


class NumberField(_FieldBase):
    type: Literal["number"]
    unit: str | None = None
    min: float | None = None
    max: float | None = None


class DateField(_FieldBase):
    type: Literal["date"]
    document_date: bool = False


class EnumField(_FieldBase):
    type: Literal["enum"]
    options: list[Option] = Field(min_length=1)

    @field_validator("options", mode="before")
    @classmethod
    def _plain_strings_to_options(cls, value):
        return [o if isinstance(o, dict) else {"value": str(o)} for o in value]


class BooleanField(_FieldBase):
    type: Literal["boolean"]


class GroupField(_FieldBase):
    type: Literal["group"]
    repeat: bool = False
    fields: list["AnyField"] = Field(min_length=1)


AnyField = Annotated[
    Union[TextField, NumberField, DateField, EnumField, BooleanField, GroupField],
    Field(discriminator="type"),
]
GroupField.model_rebuild()


def _check_unique_keys(fields: list, where: str) -> None:
    seen: set[str] = set()
    for f in fields:
        if f.key in seen:
            raise ValueError(f"duplicate field key '{f.key}' in {where}")
        seen.add(f.key)
        if isinstance(f, GroupField):
            _check_unique_keys(f.fields, f.key)


class TemplateDef(_Strict):
    key: str = Field(pattern=KEY_PATTERN)
    version: int = Field(ge=1)
    phase: Literal[1, 2, 3]
    kind: Literal["document", "film_photo", "dicom"]
    title: str
    fields: list[AnyField] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_structure(self) -> "TemplateDef":
        _check_unique_keys(self.fields, "template")
        dates = [f for f in self.fields if isinstance(f, DateField) and f.document_date]
        if len(dates) != 1:
            raise ValueError("template needs exactly one top-level date field with document_date: true")
        return self

    @property
    def document_date_key(self) -> str:
        return next(f.key for f in self.fields if isinstance(f, DateField) and f.document_date)
