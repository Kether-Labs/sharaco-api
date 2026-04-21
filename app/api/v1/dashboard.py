from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func
from app.db.engine import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.document import Document, DocumentType, DocumentStatus
from app.models.client import Client
from app.models.reminder import ReminderLog, ReminderStatus
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class DashboardStats(BaseModel):
    """Stats globales du dashboard."""
    # Compteurs
    total_clients: int = 0
    total_devis: int = 0
    total_factures: int = 0

    # Statuts devis
    devis_draft: int = 0
    devis_sent: int = 0
    devis_viewed: int = 0
    devis_paid: int = 0

    # Montants (en centimes)
    montant_total_devis_cents: int = 0
    montant_total_factures_cents: int = 0
    montant_en_attente_cents: int = 0      # SENT + VIEWED
    montant_paye_cents: int = 0             # PAID

    # Taux de conversion
    taux_conversion: Optional[float] = None  # % de devis → factures payées

    # Ce mois
    devis_ce_mois: int = 0
    factures_ce_mois: int = 0
    montant_paye_ce_mois_cents: int = 0

    # Relances
    relances_envoyees: int = 0
    relances_echouees: int = 0


class MonthlyRevenue(BaseModel):
    """CA mensuel pour les graphs."""
    month: str  # "2026-01"
    devis_count: int = 0
    factures_count: int = 0
    revenue_cents: int = 0


router = APIRouter(tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Statistiques globales du dashboard."""
    now = datetime.now(timezone.utc)
    start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    # --- Compteurs ---
    total_clients = (await db.execute(
        select(func.count(Client.id)).where(Client.user_id == current_user.id)
    )).scalar() or 0

    total_devis = (await db.execute(
        select(func.count(Document.id)).where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.DEVIS,
        )
    )).scalar() or 0

    total_factures = (await db.execute(
        select(func.count(Document.id)).where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.FACTURE,
        )
    )).scalar() or 0

    # --- Statuts devis ---
    devis_draft = (await db.execute(
        select(func.count(Document.id)).where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.DEVIS,
            Document.status == DocumentStatus.DRAFT,
        )
    )).scalar() or 0

    devis_sent = (await db.execute(
        select(func.count(Document.id)).where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.DEVIS,
            Document.status == DocumentStatus.SENT,
        )
    )).scalar() or 0

    devis_viewed = (await db.execute(
        select(func.count(Document.id)).where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.DEVIS,
            Document.status == DocumentStatus.VIEWED,
        )
    )).scalar() or 0

    devis_paid = (await db.execute(
        select(func.count(Document.id)).where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.DEVIS,
            Document.status == DocumentStatus.PAID,
        )
    )).scalar() or 0

    # --- Montants (calculé à partir des items) ---
    # Montant total des factures payées
    paid_docs = (await db.execute(
        select(Document).where(
            Document.user_id == current_user.id,
            Document.status == DocumentStatus.PAID,
        )
    )).scalars().all()

    montant_paye_cents = 0
    for doc in paid_docs:
        for item in doc.items:
            line = item.quantity * item.unit_price_cents
            tax = int(line * item.tax_rate / 100)
            montant_paye_cents += line + tax

    # Montant en attente (SENT + VIEWED)
    pending_docs = (await db.execute(
        select(Document).where(
            Document.user_id == current_user.id,
            Document.status.in_([DocumentStatus.SENT, DocumentStatus.VIEWED]),
        )
    )).scalars().all()

    montant_en_attente_cents = 0
    for doc in pending_docs:
        for item in doc.items:
            line = item.quantity * item.unit_price_cents
            tax = int(line * item.tax_rate / 100)
            montant_en_attente_cents += line + tax

    # Montant total devis
    all_devis = (await db.execute(
        select(Document).where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.DEVIS,
        )
    )).scalars().all()

    montant_total_devis_cents = 0
    for doc in all_devis:
        for item in doc.items:
            line = item.quantity * item.unit_price_cents
            tax = int(line * item.tax_rate / 100)
            montant_total_devis_cents += line + tax

    # Montant total factures
    all_factures = (await db.execute(
        select(Document).where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.FACTURE,
        )
    )).scalars().all()

    montant_total_factures_cents = 0
    for doc in all_factures:
        for item in doc.items:
            line = item.quantity * item.unit_price_cents
            tax = int(line * item.tax_rate / 100)
            montant_total_factures_cents += line + tax

    # --- Ce mois ---
    devis_ce_mois = (await db.execute(
        select(func.count(Document.id)).where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.DEVIS,
            Document.created_at >= start_of_month,
        )
    )).scalar() or 0

    factures_ce_mois = (await db.execute(
        select(func.count(Document.id)).where(
            Document.user_id == current_user.id,
            Document.type == DocumentType.FACTURE,
            Document.created_at >= start_of_month,
        )
    )).scalar() or 0

    # Montant payé ce mois
    paid_this_month = [d for d in paid_docs if d.created_at and d.created_at >= start_of_month]
    montant_paye_ce_mois_cents = 0
    for doc in paid_this_month:
        for item in doc.items:
            line = item.quantity * item.unit_price_cents
            tax = int(line * item.tax_rate / 100)
            montant_paye_ce_mois_cents += line + tax

    # --- Taux de conversion ---
    if total_devis > 0:
        taux_conversion = round((devis_paid / total_devis) * 100, 1)
    else:
        taux_conversion = None

    # --- Relances ---
    user_doc_ids = [doc.id for doc in all_devis + all_factures]
    relances_envoyees = 0
    relances_echouees = 0
    if user_doc_ids:
        relances_envoyees = (await db.execute(
            select(func.count(ReminderLog.id)).where(
                ReminderLog.document_id.in_(user_doc_ids),
                ReminderLog.status == ReminderStatus.SENT,
            )
        )).scalar() or 0

        relances_echouees = (await db.execute(
            select(func.count(ReminderLog.id)).where(
                ReminderLog.document_id.in_(user_doc_ids),
                ReminderLog.status == ReminderStatus.FAILED,
            )
        )).scalar() or 0

    return DashboardStats(
        total_clients=total_clients,
        total_devis=total_devis,
        total_factures=total_factures,
        devis_draft=devis_draft,
        devis_sent=devis_sent,
        devis_viewed=devis_viewed,
        devis_paid=devis_paid,
        montant_total_devis_cents=montant_total_devis_cents,
        montant_total_factures_cents=montant_total_factures_cents,
        montant_en_attente_cents=montant_en_attente_cents,
        montant_paye_cents=montant_paye_cents,
        taux_conversion=taux_conversion,
        devis_ce_mois=devis_ce_mois,
        factures_ce_mois=factures_ce_mois,
        montant_paye_ce_mois_cents=montant_paye_ce_mois_cents,
        relances_envoyees=relances_envoyees,
        relances_echouees=relances_echouees,
    )


@router.get("/revenue", response_model=list[MonthlyRevenue])
async def get_monthly_revenue(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Chiffre d'affaires par mois (12 derniers mois) pour les graphs."""
    now = datetime.now(timezone.utc)
    twelve_months_ago = now - timedelta(days=365)

    # Récupérer tous les documents payés des 12 derniers mois
    docs = (await db.execute(
        select(Document).where(
            Document.user_id == current_user.id,
            Document.status == DocumentStatus.PAID,
            Document.created_at >= twelve_months_ago,
        )
    )).scalars().all()

    # Grouper par mois
    monthly_data = {}
    for doc in docs:
        month_key = doc.created_at.strftime("%Y-%m")
        if month_key not in monthly_data:
            monthly_data[month_key] = {
                "month": month_key,
                "devis_count": 0,
                "factures_count": 0,
                "revenue_cents": 0,
            }

        if doc.type == DocumentType.DEVIS:
            monthly_data[month_key]["devis_count"] += 1
        else:
            monthly_data[month_key]["factures_count"] += 1

        for item in doc.items:
            line = item.quantity * item.unit_price_cents
            tax = int(line * item.tax_rate / 100)
            monthly_data[month_key]["revenue_cents"] += line + tax

    # Trier par mois
    sorted_months = sorted(monthly_data.values(), key=lambda x: x["month"])
    return [MonthlyRevenue(**m) for m in sorted_months]