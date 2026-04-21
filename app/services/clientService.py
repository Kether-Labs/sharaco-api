from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.client import Client
from uuid import UUID
from typing import Optional


class ClientService:
    @staticmethod
    async def create_client(
        db: AsyncSession,
        name: str,
        user_id: UUID,
        email: Optional[str] = None,
        address: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Client:
        client = Client(
            name=name,
            email=email,
            address=address,
            phone=phone,
            user_id=user_id,
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client

    @staticmethod
    async def get_by_id(db: AsyncSession, client_id: UUID, user_id: UUID) -> Client | None:
        """Récupère un client par ID, en vérifiant qu'il appartient à l'utilisateur."""
        statement = select(Client).where(
            Client.id == client_id,
            Client.user_id == user_id,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(
        db: AsyncSession,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Client]:
        """Liste les clients d'un utilisateur avec pagination."""
        statement = (
            select(Client)
            .where(Client.user_id == user_id)
            .order_by(Client.name)
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    @staticmethod
    async def update_client(db: AsyncSession, client: Client, **kwargs) -> Client:
        """Met à jour les champs fournis d'un client."""
        for key, value in kwargs.items():
            if value is not None and hasattr(client, key):
                setattr(client, key, value)
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client

    @staticmethod
    async def delete_client(db: AsyncSession, client: Client) -> None:
        """Supprime un client."""
        await db.delete(client)
        await db.commit()