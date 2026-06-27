from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from uuid import UUID, uuid4

class Client(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(nullable=False)
    email: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None

    user_id: UUID = Field(foreign_key="user.id")
    owner: "User" = Relationship(back_populates="clients")
    documents: List["Document"] = Relationship(back_populates="client")

    projects: List["Project"] = Relationship(back_populates="client")