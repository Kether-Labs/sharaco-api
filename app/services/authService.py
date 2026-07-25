from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.services.userService import UserService
from app.core.config import settings
from app.core.security import verify_password, create_access_token
from authlib.integrations.starlette_client import OAuth

import logging

logger = logging.getLogger(__name__)

oauth = OAuth()

oauth.register(
    name='google',
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

class AuthService:

    @staticmethod
    async def handle_google_callback(request, db: AsyncSession):
        """Gère le retour de Google après authentification."""
        try:
            # 1. Récupérer le token de Google
            token = await oauth.google.authorize_access_token(request)
            
            # 2. Récupérer les infos utilisateur via le token
            # Le champ 'userinfo' contient: email, name, picture
            user_info = token.get('userinfo')
            email = user_info.get('email')
            name = user_info.get('name', '')
            
            if not email:
                raise ValueError("Google n'a pas fourni d'email.")

            # 3. Chercher l'utilisateur en base
            from app.services.userService import UserService
            existing_user = await UserService.get_by_email(db, email)

            if existing_user:
                # ✅ CAS A : L'utilisateur existe, on le connecte
                from app.core.security import create_access_token
                access_token = create_access_token(subject=str(existing_user.id))
                
                return {
                    "action": "login",
                    "access_token": access_token,
                    "redirect_url": f"{settings.FRONTEND_URL}/dashboard"
                }
            
            else:
                # ✅ CAS B : Nouvel utilisateur, on génère un token temporaire
                import uuid
                from datetime import datetime, timedelta, timezone
                
                temp_token = str(uuid.uuid4())
                expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
                
                # TODO: Sauvegarder ce temp_token en base ou Redis avec les infos Google
                # Pour l'instant, on le passe en paramètre d'URL (moins sécurisé mais simple pour démarrer)
                # Idéalement : stocker {temp_token: {"email": email, "name": name}} en Redis
                
                return {
                    "action": "complete_profile",
                    "temp_token": temp_token,
                    "email": email,
                    "full_name": name,
                    "redirect_url": f"{settings.FRONTEND_URL}/register/complete-profile?token={temp_token}&email={email}&name={name}"
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
        
        
        return user is not None
