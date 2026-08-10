# app/api/routes/payment_schedule.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from uuid import UUID
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.documentService import DocumentService
from app.services.paymentScheduleService import PaymentScheduleService

router = APIRouter(tags=["payment-schedule"])


class MilestoneInput(BaseModel):
    sequence: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    percent: float = Field(ge=0, le=100)
    description: Optional[str] = None
    trigger_date: Optional[datetime] = None


class SetScheduleRequest(BaseModel):
    milestones: list[MilestoneInput]


class MilestoneRead(BaseModel):
    id: UUID
    sequence: int
    title: str
    percent: float
    amount_cents: int
    description: Optional[str]
    trigger_date: Optional[datetime]
    status: str
    invoice_id: Optional[UUID]
    invoiced_at: Optional[datetime]
    paid_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.get("/", response_model=list[MilestoneRead])
async def get_schedule(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupère l'échéancier d'un devis."""
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return await PaymentScheduleService.get_by_document(db, document_id)


@router.put("/", response_model=list[MilestoneRead])
async def set_schedule(
    document_id: UUID,
    payload: SetScheduleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Définit/remplace l'échéancier d'un devis."""
    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")
    
    try:
        milestones_data = [m.model_dump() for m in payload.milestones]
        return await PaymentScheduleService.set_schedule(db, document, milestones_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{milestone_id}/invoice")
async def invoice_milestone(
    document_id: UUID,
    milestone_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Génère une facture pour une échéance spécifique."""
    from sqlmodel import select
    from app.models.payment_schedule import PaymentSchedule

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    result = await db.execute(
        select(PaymentSchedule).where(
            PaymentSchedule.id == milestone_id,
            PaymentSchedule.document_id == document_id,
        )
    )
    milestone = result.scalar_one_or_none()
    if not milestone:
        raise HTTPException(status_code=404, detail="Échéance introuvable")

    try:
        invoice = await PaymentScheduleService.invoice_milestone(
            db, milestone, document, origin="manual"
        )
        await db.commit()
        return {
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.number,
            "milestone": milestone.title,
            "amount_cents": milestone.amount_cents,
        }
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{milestone_id}/mark-paid")
async def mark_milestone_paid(
    document_id: UUID,
    milestone_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Marque une échéance comme payée."""
    from sqlmodel import select
    from app.models.payment_schedule import PaymentSchedule

    document = await DocumentService.get_by_id(db, document_id, current_user.id)
    if not document:
        raise HTTPException(status_code=404, detail="Document introuvable")

    result = await db.execute(
        select(PaymentSchedule).where(
            PaymentSchedule.id == milestone_id,
            PaymentSchedule.document_id == document_id,
        )
    )
    milestone = result.scalar_one_or_none()
    if not milestone:
        raise HTTPException(status_code=404, detail="Échéance introuvable")

    try:
        await PaymentScheduleService.mark_as_paid(db, milestone)
        await db.commit()
        return {"status": "paid", "milestone_id": str(milestone.id)}
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))