# app/utils/email.py

import unicodedata
import re


def normalize_email(email: str) -> str:
    """
    Normalise un email pour le stockage et la recherche.
    
    Opérations :
    1. Supprime les espaces avant/après
    2. Convertit en minuscules
    3. Normalise les caractères Unicode (accents, etc.)
    4. Valide le format basique
    
    Args:
        email: L'email à normaliser
        
    Returns:
        L'email normalisé
        
    Example:
        >>> normalize_email("  User@Example.COM  ")
        'user@example.com'
        >>> normalize_email("user@exämple.com")
        'user@xample.com'  # après normalisation NFKC
    """
    if not email:
        return ""
    
    # 1. Supprimer espaces avant/après
    email = email.strip()
    
    # 2. Convertir en minuscules
    email = email.lower()
    
    # 3. Normaliser Unicode (accents, caractères spéciaux)
    email = unicodedata.normalize('NFKC', email)
    
    # 4. Validation basique (optionnel mais recommandé)
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        raise ValueError(f"Format d'email invalide: {email}")
    
    return email


def is_valid_email(email: str) -> bool:
    """
    Vérifie si un email a un format valide.
    
    Args:
        email: L'email à vérifier
        
    Returns:
        True si valide, False sinon
    """
    if not email:
        return False
    
    # Regex simple mais efficace
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))