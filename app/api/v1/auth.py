from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.engine import get_db
from app.services.authService import AuthService
from app.services.userService import UserService
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, Token

router = APIRouter(tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """Inscription d'un nouvel utilisateur."""
    # Vérifier si l'email est déjà pris
    existing = await UserService.get_by_email(db, user_data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un compte avec cet email existe déjà",
        )

    user = await UserService.create_user(
        db=db,
        email=user_data.email,
        password=user_data.password,
        company_name=user_data.company_name,
        address=user_data.address,
        tax_id=user_data.tax_id,
        payment_info=user_data.payment_info,
    )
    return user


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