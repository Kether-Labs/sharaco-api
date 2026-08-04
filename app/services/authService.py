from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.services.userService import UserService
from app.core.config import settings
from app.core.security import verify_password, create_access_token
from app.core.oauth import oauth
from datetime import datetime, timedelta, timezone

import logging

logger = logging.getLogger(__name__)





class AuthService:

    @staticmethod
    async def handle_google_callback(request, db):
        """Gère le retour de Google après authentification."""
        try:
            # 1. Récupérer le token et les infos de Google
            token = await oauth.google.authorize_access_token(request)
            user_info = token.get('userinfo')
            email = user_info.get('email')
            name = user_info.get('name', '')
            
            if not email:
                raise ValueError("Google n'a pas fourni d'email.")

            # 2. Chercher l'utilisateur en base
            existing_user = await UserService.get_by_email(db, email)

            if existing_user:
                # ✅ CAS A : L'utilisateur existe, on le connecte
                access_token = create_access_token(subject=str(existing_user.id))
                return {
                    "action": "login",
                    "access_token": access_token,
                }
            
            else:
                # ✅ CAS B : Nouvel utilisateur, on génère un token temporaire signé
                temp_token = create_access_token(
                    subject=email, 
                    extra_claims={
                        "type": "oauth_temp", 
                        "name": name,
                        "exp": (datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()
                    }
                )
                
                return {
                    "action": "complete_profile",
                    "temp_token": temp_token,
                    "email": email,
                    "name": name,
                }

        except Exception as e:
            logger.error(f"❌ Erreur OAuth Google: {e}", exc_info=True)
            raise ValueError("Échec de l'authentification Google")
    @staticmethod
    async def authenticate(db: AsyncSession, email: str, password: str):
        user = await UserService.get_by_email(db, email)

        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou mot de passe incorrect",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = create_access_token(subject=str(user.id))
        return {"access_token": token, "token_type": "bearer"}

    async def verifyIfEmailExist(db: AsyncSession, email: str):
        user = await UserService.get_by_email(db, email)
        
        
        if not user:
            
            return False
        return True
        
