from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.document import DocumentType, DocumentStatus
from app.services.documentService import DocumentService
from app.schemas.document import (
    DocumentCreate,
    DocumentRead,
    DocumentUpdate,
    DocumentStatusUpdate,
    DocumentListRead,
)

router = APIRouter(tags=["documents"])


def _enrich_document(doc, totals: dict) -> dict:
    """Ajoute les totaux calculés au document pour le schema de retour."""
    data = {
        "id": doc.id,
        "type": doc.type,
        "status": doc.status,
        "number": doc.number,
        "created_at": doc.created_at,
        "due_date": doc.due_date,
        "user_id": doc.user_id,
        "client_id": doc.client_id,
        "template_id": doc.template_id,
        "items": doc.items,
        "subtotal_cents": totals["subtotal_cents"],
        "tax_total_cents": totals["tax_total_cents"],
        "grand_total_cents": totals["grand_total_cents"],
    }
    return data


@router.post("/", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    document_data: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Créer un nouveau devis ou facture."""
    # Vérifier que le client appartient à l'utilisateur
    from app.services.clientService import ClientService
    client = await ClientService.get_by_id(db, document_data.client_id, current_user.id)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client introuvable",
        )

    try:
        document = await DocumentService.create_document(
            db=db,
            type=document_data.type,
            user_id=current_user.id,
            client_id=document_data.client_id,
            items=[item.model_dump() for item in document_data.items],
            template_id=document_data.template_id,
            due_date=document_data.due_date,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    totals = DocumentService.calculate_totals(document.items)
    return _enrich_document(document, totals)


@router.get("/", response_model=list[DocumentListRead])
async def list_documents(
    type: Optional[DocumentType] = Query(None, description="Filtrer par type"),
    status: Optional[DocumentStatus] = Query(None, description="Filtrer par statut"),
    client_id: Optional[UUID] = Query(None, description="Filtrer par client"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Liste les documents avec filtres et pagination."""
    documents = await DocumentService.get_all(
        db=db,
        user_id=current_user.id,
        type=type,
        status=status,
        client_id=client_id,
        skip=skip,
        limit=limit,
    )

    # Enrichir avec les totaux
    result = []
    for doc in documents:
        totals = DocumentService.calculate_totals(doc.items)
        result.append({
            "id": doc.id,
            "type": doc.type,
            "status": doc.status,
            "number": doc.number,
            "created_at": doc.created_at,
            "due_date": doc.due_date,
            "client_id": doc.client_id,
            "template_id": doc.template_id,
            "grand_total_cents": totals["grand_total_cents"],
        })
    return result


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupérer les détails complets d'un document avec totaux."""
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    totals = DocumentService.calculate_totals(document.items)
    return _enrich_document(document, totals)


@router.put("/{document_id}", response_model=DocumentRead)
async def update_document(
    document_id: UUID,
    document_data: DocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Modifier un document (échéance, template)."""
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    try:
        updated = await DocumentService.update_document(
            db=db,
            document=document,
            due_date=document_data.due_date,
            template_id=document_data.template_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    totals = DocumentService.calculate_totals(updated.items)
    return _enrich_document(updated, totals)


@router.patch("/{document_id}/status", response_model=DocumentRead)
async def update_document_status(
    document_id: UUID,
    status_data: DocumentStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Changer le statut d'un document (DRAFT→SENT→PAID)."""
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    try:
        updated = await DocumentService.update_status(
            db=db,
            document=document,
            new_status=status_data.status,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    totals = DocumentService.calculate_totals(updated.items)
    return _enrich_document(updated, totals)


@router.post("/{document_id}/convert", response_model=DocumentRead)
async def convert_to_invoice(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Convertir un devis en facture (duplique avec nouveau numéro)."""
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    try:
        invoice = await DocumentService.duplicate_as_invoice(db, document)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    totals = DocumentService.calculate_totals(invoice.items)
    return _enrich_document(invoice, totals)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Supprimer un document (uniquement si DRAFT)."""
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable",
        )

    try:
        await DocumentService.delete_document(db, document)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
