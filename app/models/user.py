from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from uuid import UUID, uuid4

class User(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(unique=True, index=True, nullable=False)
    hashed_password: str = Field(nullable=False)

    company_name: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None  # SIRET, NIF, etc.
    payment_info: Optional[str] = None # IBAN, Mobile Money, etc.

    full_name: Optional[str] = Field(default=None, max_length=100)
    clients: List["Client"] = Relationship(back_populates="owner")
    documents: List["Document"] = Relationship(back_populates="owner")
    templates: List["DocumentTemplate"] = Relationship(back_populates="owner")
    reminder_configs: List["ReminderConfig"] = Relationship(back_populates="owner")

    projects: List["Project"] = Relationship(back_populates="owner")