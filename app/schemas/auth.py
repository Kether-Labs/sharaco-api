# app/schemas/auth.py

from pydantic import BaseModel, EmailStr, Field, field_validator
import re

class RegisterRequest(BaseModel):
    """Schéma pour l'inscription."""
    email: EmailStr = Field(..., description="Email de connexion")
    password: str = Field(..., min_length=8, description="Mot de passe (min 8 caractères)")
    full_name: str = Field(..., min_length=2, max_length=100, description="Nom complet")
    company_name: str = Field(..., min_length=2, max_length=100, description="Nom de l'entreprise")
    phone: str | None = Field(None, max_length=20, description="Téléphone (optionnel)")
    
    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalise l'email."""
        return v.strip().lower()
    
    @field_validator("password", mode="before")
    @classmethod
    def validate_password(cls, v):
        if not isinstance(v, str):
            raise ValueError("Le mot de passe doit être une chaîne")
        
        v = v.strip()
        
        if len(v) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
        
        if len(v) > 128:
            raise ValueError("Le mot de passe est trop long (max 128 caractères)")
        
        return v
    
    @field_validator("full_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Valide le nom."""
        v = v.strip()
        if len(v.split()) < 2:
            raise ValueError("Veuillez entrer votre nom complet (prénom et nom)")
        return v


class RegisterResponse(BaseModel):
    """Réponse après inscription."""
    message: str
    user_id: str
    access_token: str
    token_type: str = "bearer"