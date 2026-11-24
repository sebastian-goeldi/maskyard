from typing import Any

from sqlmodel import JSON, Field, SQLModel


class InfoBase(SQLModel):
    id: int | None = Field(default=None, primary_key=True)
    data: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
