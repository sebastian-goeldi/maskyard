from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel

CURRENT_SCHEMA_VERSION = 2


class DatabaseConfig(SQLModel, table=True):
    __table_args__ = (CheckConstraint("id = 1"),)

    id: int = Field(default=1, primary_key=True)
    dbu: float
    schema_version: int = Field(default=CURRENT_SCHEMA_VERSION)
