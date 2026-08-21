# app/schemas/project_tree.py
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, List


class ProjectTreeQuoteSummary(BaseModel):
    """Stats d'un devis spécifique."""
    quoted_amount: int  # montant total du devis (centimes)
    invoiced_amount: int  # total déjà facturé
    paid_amount: int  # total payé
    overdue_amount: int  # total en retard
    pending_amount: int  # reste à facturer


class ProjectTreeMilestone(BaseModel):
    """Milestone lié à un devis."""
    id: UUID
    sequence: int
    title: str
    percent: float
    amount_cents: int
    description: Optional[str] = None
    trigger_date: Optional[datetime] = None
    status: str  # PENDING, INVOICED, PAID, CANCELLED
    invoice_id: Optional[UUID] = None


class ProjectTreeInvoice(BaseModel):
    """Facture associée à un devis."""
    id: UUID
    number: Optional[str] = None
    invoice_type: Optional[str] = None  # ACOMPTE, SOLDE, STANDARD
    status: str
    due_date: Optional[datetime] = None
    issued_at: Optional[datetime] = None  # created_at de la facture
    amount_cents: int  # montant TTC
    milestone_id: Optional[UUID] = None  # si liée à un milestone
    milestone_title: Optional[str] = None
    days_late: Optional[int] = None  # si OVERDUE


class ProjectTreeQuote(BaseModel):
    """Devis avec ses factures."""
    id: UUID
    number: Optional[str] = None
    status: str
    created_at: datetime
    accepted_at: Optional[datetime] = None
    amount_cents: int  # montant TTC total du devis
    milestones: List[ProjectTreeMilestone] = []
    invoices: List[ProjectTreeInvoice] = []
    summary: ProjectTreeQuoteSummary


class ProjectTreeStandaloneInvoice(BaseModel):
    """Facture non liée à un devis (si ex.)."""
    id: UUID
    number: Optional[str] = None
    status: str
    due_date: Optional[datetime] = None
    amount_cents: int
    days_late: Optional[int] = None


class ProjectTreeSummary(BaseModel):
    """Stats agrégées du projet entier."""
    total_quoted: int
    total_invoiced: int
    total_paid: int
    total_overdue: int
    total_pending: int
    quote_count: int
    invoice_count: int
    paid_invoice_count: int
    overdue_invoice_count: int
    invoicing_rate: float  # % facturé vs devisé
    collection_rate: float  # % payé vs facturé


class ProjectTreeResponse(BaseModel):
    """Arborescence complète d'un projet."""
    project_id: UUID
    project_name: str
    client_id: Optional[UUID] = None
    client_name: Optional[str] = None
    quotes: List[ProjectTreeQuote] = []
    standalone_invoices: List[ProjectTreeStandaloneInvoice] = []
    summary: ProjectTreeSummary