from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID


class ClientCreate(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    phone: Optional[str] = None


class ClientRead(BaseModel):
    id: UUID
    name: str
    email: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None

    model_config = {"from_attributes": True}


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    phone: Optional[str] = None