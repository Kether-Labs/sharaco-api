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
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Valide la force du mot de passe."""
        if not re.search(r"[A-Z]", v):
            raise ValueError("Le mot de passe doit contenir au moins une majuscule")
        if not re.search(r"[a-z]", v):
            raise ValueError("Le mot de passe doit contenir au moins une minuscule")
        if not re.search(r"\d", v):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")
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