# app/schemas/project_overview.py
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, List
from app.schemas.project_overview import ProjectOverviewResponse

class ProjectOverviewStats(BaseModel):
    """Stats agrégées d'un projet."""
    quote_count: int
    accepted_quote_count: int
    invoice_count: int
    paid_invoice_count: int
    overdue_invoice_count: int
    
    total_quoted: int  # total des devis (centimes)
    total_invoiced: int  # total des factures émises
    total_paid: int  # total encaissé
    total_overdue: int  # total en retard
    
    invoicing_rate: float  # % facturé vs devisé
    collection_rate: float  # % encaissé vs facturé


class ProjectOverviewItem(BaseModel):
    """Projet avec stats résumées."""
    id: UUID
    name: str
    description: Optional[str] = None
    created_at: datetime
    client_id: Optional[UUID] = None
    client_name: Optional[str] = None
    
    # Statut global du projet (dérivé)
    has_overdue: bool  # True si au moins 1 facture en retard
    is_fully_paid: bool  # True si toutes les factures sont payées
    
    stats: ProjectOverviewStats


class ProjectOverviewResponse(BaseModel):
    """Liste des projets avec stats."""
    total_projects: int
    projects: List[ProjectOverviewItem]
    
    # Stats globales de tous les projets
    global_summary: dict