# app/core/oauth.py

from authlib.integrations.starlette_client import OAuth
from app.core.config import settings

oauth = OAuth()

oauth.register(
    name='google',
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    # ✅ OBLIGATOIRE pour que Authlib puisse valider le token Google
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile',
        'timeout': 30.0,  # ✅ 30 secondes (largeur maximale pour éviter les timeouts réseau)
    },
)