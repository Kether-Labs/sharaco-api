# app/models/project.py
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Enums Python uniquement (pas en DB)
class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"
    CANCELLED = "CANCELLED"


class AttachmentType(str, Enum):
    CDC = "CDC"
    CONTRACT = "CONTRACT"
    SPEC = "SPEC"
    OTHER = "OTHER"


class Project(SQLModel, table=True):
    __tablename__ = "project"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    description: Optional[str] = None
    
    # ✅ SIMPLE : juste un string (20 caractères max)
    status: str = Field(
        default=ProjectStatus.DRAFT.value,
        max_length=20,
        description="DRAFT, ACTIVE, COMPLETED, ARCHIVED, CANCELLED"
    )
    
    budget_cents: Optional[int] = Field(default=None)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    
    created_at: datetime = Field(default_factory=_utcnow_naive)
    updated_at: datetime = Field(default_factory=_utcnow_naive)
    
    user_id: UUID = Field(foreign_key="user.id")
    owner: "User" = Relationship(back_populates="projects")
    
    client_id: UUID = Field(foreign_key="client.id")
    client: "Client" = Relationship(back_populates="projects")
    
    documents: List["Document"] = Relationship(back_populates="project")
    attachments: List["ProjectAttachment"] = Relationship(back_populates="project")
    
    # Helper pour valider le statut
    def get_status_enum(self) -> ProjectStatus:
        return ProjectStatus(self.status)
    
    def set_status(self, status: ProjectStatus):
        self.status = status.value


class ProjectAttachment(SQLModel, table=True):
    __tablename__ = "project_attachment"
    
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    file_url: str
    
    # ✅ SIMPLE : juste un string
    file_type: str = Field(
        default=AttachmentType.OTHER.value,
        max_length=20,
        description="CDC, CONTRACT, SPEC, OTHER"
    )
    
    uploaded_at: datetime = Field(default_factory=_utcnow_naive)
    
    project_id: UUID = Field(foreign_key="project.id")
    project: Project = Relationship(back_populates="attachments")
    
    user_id: UUID = Field(foreign_key="user.id")
    
    def get_type_enum(self) -> AttachmentType:
        return AttachmentType(self.file_type)