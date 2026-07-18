from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.engine import get_db
from app.services.authService import AuthService
from app.services.userService import UserService
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, Token
from app.core.security import verify_password, create_access_token
import logging
from app.schemas.auth import RegisterRequest, RegisterResponse


router = APIRouter(tags=["auth"])


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
        access_token = create_access_token(data={"sub": str(user.id)})
        
        return RegisterResponse(
            message="Compte créé avec succès",
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


@router.get("/me", response_model=UserRead)
async def read_current_user(
    current_user: User = Depends(get_current_user),
):
    """Retourne le profil de l'utilisateur connecté."""
    return current_user

@router.post("/verify-email")
async def verify_email(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Vérifie si l'email est déjà pris."""
    return await AuthService.verifyIfEmailExist(db, email)