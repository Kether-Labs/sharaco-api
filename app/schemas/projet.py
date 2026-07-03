# app/schemas/project.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from app.models.projet import ProjectStatus, AttachmentType


class ProjectAttachmentRead(BaseModel):
    """Schéma de lecture pour les attachments."""
    id: UUID
    name: str
    file_url: str
    file_type: str
    uploaded_at: datetime
    project_id: UUID
    user_id: UUID

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    """Création d'un projet."""
    name: str = Field(..., min_length=1, max_length=255, description="Nom du projet")
    description: Optional[str] = Field(None, max_length=2000)
    status: str = Field(default="DRAFT", max_length=20)
    budget_cents: Optional[int] = Field(None, ge=0, description="Budget estimé en centimes")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    client_id: UUID = Field(..., description="ID du client associé")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        valid = [s.value for s in ProjectStatus]
        if v not in valid:
            raise ValueError(f"Status invalide. Options: {', '.join(valid)}")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: Optional[datetime], info) -> Optional[datetime]:
        if v and info.data.get("start_date") and v < info.data["start_date"]:
            raise ValueError("La date de fin doit être après la date de début")
        return v


class ProjectUpdate(BaseModel):
    """Mise à jour d'un projet."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    status: Optional[str] = Field(None, max_length=20)
    budget_cents: Optional[int] = Field(None, ge=0)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    client_id: Optional[UUID] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        valid = [s.value for s in ProjectStatus]
        if v not in valid:
            raise ValueError(f"Status invalide. Options: {', '.join(valid)}")
        return v

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: Optional[datetime], info) -> Optional[datetime]:
        if v and info.data.get("start_date") and v < info.data["start_date"]:
            raise ValueError("La date de fin doit être après la date de début")
        return v


class ProjectRead(BaseModel):
    """Lecture complète d'un projet."""
    id: UUID
    name: str
    description: Optional[str] = None
    status: str
    budget_cents: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    user_id: UUID
    client_id: UUID
    
    # Relations optionnelles
    documents_count: Optional[int] = None
    attachments: Optional[List[ProjectAttachmentRead]] = None

    model_config = {"from_attributes": True}


class ProjectListRead(BaseModel):
    """Lecture simplifiée pour les listes."""
    id: UUID
    name: str
    description: Optional[str] = None
    status: str
    budget_cents: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    created_at: datetime
    client_id: UUID
    client_name: Optional[str] = None
    documents_count: Optional[int] = None
    total_invoiced_cents: Optional[int] = None

    model_config = {"from_attributes": True}


class ProjectAttachmentCreate(BaseModel):
    """Création d'un attachment."""
    name: str = Field(..., min_length=1, max_length=255)
    file_url: str = Field(..., min_length=1)
    file_type: str = Field(default="OTHER", max_length=20)

    @field_validator("file_type")
    @classmethod
    def validate_file_type(cls, v: str) -> str:
        valid = [t.value for t in AttachmentType]
        if v not in valid:
            raise ValueError(f"Type invalide. Options: {', '.join(valid)}")
        return v