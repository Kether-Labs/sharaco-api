# app/schemas/project.py
from pydantic import BaseModel, field_validator

class ProjectCreate(BaseModel):
    name: str
    status: str = "DRAFT"
    
    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        valid = ["DRAFT", "ACTIVE", "COMPLETED", "ARCHIVED", "CANCELLED"]
        if v not in valid:
            raise ValueError(f"Status invalide. Options: {valid}")
        return v