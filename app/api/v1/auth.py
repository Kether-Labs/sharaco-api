from fastapi import APIRouter, Depends, HTTPException, status,Request
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.engine import get_db
from app.services.authService import AuthService
from app.core.security import verify_password, get_password_hash
from sqlmodel import select
from app.services.userService import UserService
import secrets
from app.core.security import create_access_token, decode_access_token,hash_password
from app.core.deps import get_current_user
from app.core.config import settings
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, Token,UserUpdate,PasswordUpdate
from app.core.security import verify_password, create_access_token
import logging
from app.schemas.auth import RegisterRequest, RegisterResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from authlib.integrations.starlette_client import OAuth
from pydantic import BaseModel
from app.core.oauth import oauth
from app.utils.emails import normalize_email
limiter = Limiter(key_func=get_remote_address)



oauth.register(
    name='google',
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)
router = APIRouter(tags=["auth"])

class CompleteGoogleRegistrationRequest(BaseModel):
    temp_token: str
    full_name: str
    company_name: str | None = None
    phone: str | None = None

logger = logging.getLogger(__name__)

@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Inscription d'un nouvel utilisateur."""
    logger.info(f"📝 POST /auth/register - Email: {data.email}")
    
    try:
        # Créer l'utilisateur
        user = await UserService.register_user(db, data)
        
        # Générer le token JWT (auto-login après inscription)
        access_token = create_access_token(subject=str(user.id))
        
        return RegisterResponse(
            message="Compte créé avec succès",
            token_type="bearer",
            user_id=str(user.id),
            access_token=access_token,
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"❌ Erreur inscription: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la création du compte"
        )


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Connexion avec email + mot de passe. Retourne un JWT."""
    return await AuthService.authenticate(
        db=db,
        email=form_data.username,
        password=form_data.password,
    )

@router.post("/complete-google-registration", response_model=RegisterResponse)
async def complete_google_registration(
    data: CompleteGoogleRegistrationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Finalise l'inscription d'un utilisateur venu de Google."""
    try:
        payload = decode_access_token(data.temp_token)
        
        if payload.get("type") != "oauth_temp":
            raise HTTPException(status_code=400, detail="Token d'inscription invalide ou expiré")
        
        email = payload.get("sub")
        name_from_token = payload.get("name", "")
        
        if not email:
            raise HTTPException(status_code=400, detail="Email manquant dans le token")

        existing = await UserService.get_by_email(db, email)
        if existing:
            
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

        random_password = secrets.token_urlsafe(32)
        
        user = User(
            email=normalize_email(email),
            hashed_password=hash_password(random_password),
            full_name=data.full_name.strip() or name_from_token,
            company_name=data.company_name.strip() if data.company_name else None,
            phone=data.phone.strip() if data.phone else None,
            is_active=True,
            is_verified=True,
        )
        
        db.add(user)
        await db.commit()
        await db.refresh(user)

        
        
        # 4. Générer le VRAI token JWT de connexion
        access_token = create_access_token(subject=str(user.id))
        
        logger.info(f"✅ Inscription Google finalisée: {user.email}")
        
        return RegisterResponse(
            message="Compte créé avec succès",
            user_id=str(user.id),
            access_token=access_token,
            token_type="bearer",
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur finalisation Google: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erreur interne lors de la création du compte")

@router.get("/google/login")
async def google_login(request: Request):
    """Redirige l'utilisateur vers la page de connexion Google."""
    redirect_uri = "http://localhost:8000/api/v1/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Reçoit le callback de Google et redirige vers le frontend."""
    try:
        result = await AuthService.handle_google_callback(request, db)
        
        if result["action"] == "login":
            print(f"✅ dddz {settings.FRONTEND_URL}/dashboard?token={result['access_token']}")
            return RedirectResponse(
                url=f"{settings.FRONTEND_URL}/dashboard?token={result['access_token']}"
            )
        else:
            temp_token = result.get("temp_token")
            email = result.get("email")
            name = result.get("name", "")
            
            redirect_url = f"{settings.FRONTEND_URL}/signup?oauth_token={temp_token}&email={email}&name={name}"
            return RedirectResponse(url=redirect_url)
            
    except Exception as e:
        logger.error(f"Erreur callback Google: {e}")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=google_auth_failed")



@router.get("/me", response_model=UserRead)
async def read_current_user(
    current_user: User = Depends(get_current_user),
):
    """Retourne le profil de l'utilisateur connecté."""
    return current_user

@router.put("/me", response_model=UserRead)
async def update_profile(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Met à jour le profil (infos perso + entreprise)."""
    update_data = data.model_dump(exclude_unset=True)

    # Vérifier l'unicité si l'email change
    new_email = update_data.get("email")
    if new_email and new_email != current_user.email:
        existing = await db.execute(
            select(User).where(User.email == new_email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

    # Appliquer les champs fournis
    for field, value in update_data.items():
        setattr(current_user, field, value)

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    logger.info(f"✅ Profil mis à jour: {current_user.email}")
    return current_user

@router.put("/me/password")
async def change_password(
    data: PasswordUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change le mot de passe."""
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Le nouveau mot de passe doit faire au moins 6 caractères")

    current_user.hashed_password = get_password_hash(data.new_password)
    db.add(current_user)
    await db.commit()

    logger.info(f"🔒 Mot de passe changé: {current_user.email}")
    return {"message": "Mot de passe mis à jour avec succès"}

@router.post("/verify-email",response_model=bool)
@limiter.limit("10/minute") 
async def verify_email(
    request:Request,
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Vérifie si l'email est déjà pris."""

    normalized_email = email.strip().lower()
    
    # Vérifier le format
    import re
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", normalized_email):
        return False

    user = await AuthService.verifyIfEmailExist(db, email)
    if user:
        return True
    return False