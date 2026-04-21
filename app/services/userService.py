from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.core.security import get_password_hash
from typing import Optional


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
    async def get_by_email(db: AsyncSession, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

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