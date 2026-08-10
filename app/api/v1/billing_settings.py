# app/api/routes/billing_settings.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.billingSettingsService import BillingSettingsService

router = APIRouter(tags=["billing-settings"])


class BillingSettingsRead(BaseModel):
    auto_create_invoice: bool
    auto_send_invoice: bool
    acompte_percent: Optional[float]
    invoice_prefix: str
    invoice_number_format: str
    default_payment_terms_days: int
    default_late_fee_percent: float
    legal_mentions: Optional[str]

    class Config:
        from_attributes = True


class BillingSettingsUpdate(BaseModel):
    auto_create_invoice: Optional[bool] = None
    auto_send_invoice: Optional[bool] = None
    acompte_percent: Optional[float] = Field(default=None, ge=0, le=100)
    invoice_prefix: Optional[str] = None
    invoice_number_format: Optional[str] = None
    default_payment_terms_days: Optional[int] = None
    default_late_fee_percent: Optional[float] = None
    legal_mentions: Optional[str] = None


@router.get("/", response_model=BillingSettingsRead)
async def get_billing_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Récupère les paramètres de facturation de l'utilisateur."""
    settings = await BillingSettingsService.get_or_create(db, current_user.id)
    return settings


@router.patch("/", response_model=BillingSettingsRead)
async def update_billing_settings(
    payload: BillingSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Met à jour les paramètres de facturation."""
    try:
        data = payload.model_dump(exclude_unset=True)
        settings = await BillingSettingsService.update(db, current_user.id, **data)
        return settings
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))