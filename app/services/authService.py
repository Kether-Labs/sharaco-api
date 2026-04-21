from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.services.userService import UserService
from app.core.security import verify_password, create_access_token


class AuthService:
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
