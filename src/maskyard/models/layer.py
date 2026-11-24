from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Layer(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("layer", "datatype"),
        UniqueConstraint("name"),
    )
    id: int | None = Field(default=None, primary_key=True)
    layer: int
    datatype: int
    name: str | None = None
