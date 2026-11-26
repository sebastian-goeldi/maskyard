from sqlmodel import JSON, Field, SQLModel

from ..typing import JSONSerializable


class InfoBase(SQLModel):
    id: int | None = Field(default=None, primary_key=True)
    data: dict[str, JSONSerializable] = Field(default_factory=dict, sa_type=JSON)
