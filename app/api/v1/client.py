from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.clientService import ClientService
from app.schemas.client import ClientCreate, ClientRead, ClientUpdate

router = APIRouter(tags=["clients"])


@router.post("/", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
async def create_client(
    client_data: ClientCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Créer un nouveau client."""
    client = await ClientService.create_client(
        db=db,
        name=client_data.name,
        user_id=current_user.id,
        email=client_data.email,
        address=client_data.address,
        phone=client_data.phone,
    )
    return client


@router.get("/", response_model=list[ClientRead])
async def list_clients(
    skip: int = Query(0, ge=0, description="Nombre de résultats à sauter"),
    limit: int = Query(50, ge=1, le=100, description="Nombre max de résultats"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Liste tous les clients de l'utilisateur connecté (paginé)."""
    clients = await ClientService.get_all(
        db=db,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )
    return clients


@router.get("/{client_id}", response_model=ClientRead)
async def get_client(
    client_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupérer les détails d'un client."""
    client = await ClientService.get_by_id(db, client_id, current_user.id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client introuvable",
        )
    return client


@router.put("/{client_id}", response_model=ClientRead)
async def update_client(
    client_id: UUID,
    client_data: ClientUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Modifier un client existant."""
    client = await ClientService.get_by_id(db, client_id, current_user.id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client introuvable",
        )

    updated = await ClientService.update_client(
        db=db,
        client=client,
        name=client_data.name,
        email=client_data.email,
        address=client_data.address,
        phone=client_data.phone,
    )
    return updated


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Supprimer un client."""
    client = await ClientService.get_by_id(db, client_id, current_user.id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client introuvable",
        )

    await ClientService.delete_client(db, client)
