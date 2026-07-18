from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.core.security import get_password_hash
from typing import Optional
from app.schemas.auth import RegisterRequest
from app.core.security import hash_password
from app.utils.emails import normalize_email

class UserService:
    @staticmethod
    async def create_user(
        db: AsyncSession,
        email: str,
        password: str,
        company_name: Optional[str] = None,
        address: Optional[str] = None,
        tax_id: Optional[str] = None,
        payment_info: Optional[str] = None,
    ) -> User:
        hashed_pwd = get_password_hash(password)
        db_user = User(
            email=email,
            hashed_password=hashed_pwd,
            company_name=company_name,
            address=address,
            tax_id=tax_id,
            payment_info=payment_info,
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user


    @staticmethod
    async def register_user(db: AsyncSession, data: RegisterRequest) -> User:
        """Crée un nouvel utilisateur."""
        
        # 1. Vérifier que l'email n'existe pas déjà
        existing = await UserService.get_by_email(db, data.email)
        if existing:
            raise ValueError("Cet email est déjà utilisé")
        
        # 2. Créer l'utilisateur
        user = User(
            email=normalize_email(data.email),
            hashed_password=hash_password(data.password),
            full_name=data.full_name.strip(),
            company_name=data.company_name.strip(),
            phone=data.phone.strip() if data.phone else None,
            is_active=True,
            is_verified=False,  # Pour plus tard (vérification email)
        )
        
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
        
        
        return user
    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> User | None:
        normalized_email = email.strip().lower()
        statement = select(User).where(User.email == normalized_email)
        
        result = await db.execute(statement)
        user = result.scalar_one_or_none()  # ✅ Une seule fois
        
        
        return user

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: str) -> User | None:
        statement = select(User).where(User.id == user_id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_user(db: AsyncSession, user: User, **kwargs) -> User:
        """Met à jour les champs fournis d'un utilisateur."""
        for key, value in kwargs.items():
            if value is not None and hasattr(user, key):
                setattr(user, key, value)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user