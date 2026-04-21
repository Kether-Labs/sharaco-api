from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
from datetime import datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    company_name: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    payment_info: Optional[str] = None


class UserRead(BaseModel):
    id: UUID
    email: str
    company_name: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    payment_info: Optional[str] = None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    company_name: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    payment_info: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[str] = None