# app/services/projectService.py
from sqlmodel import select, func, col, or_
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.payment_schedule import PaymentSchedule
from app.models.projet import Project, ProjectAttachment, ProjectStatus
from app.models.document import Document, DocumentType, DocumentStatus, DocumentItem
from app.utils.datetime import to_naive_utc
from app.models.client import Client
from app.services.documentService import DocumentService
from uuid import UUID
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


class ProjectService:
    
    @staticmethod
    async def get_projects_overview(
        db: AsyncSession, 
        user_id: UUID
    ) -> dict:
        """
        Retourne tous les projets de l'utilisateur avec stats agrégées.
        ✅ CORRIGÉ : prend en compte les factures liées via source_document_id
        """
        # ═══════════════════════════════════════════════════════════
        # 1. Charger tous les projets de l'utilisateur
        # ═══════════════════════════════════════════════════════════
        projects_stmt = (
            select(Project)
            .options(selectinload(Project.client))
            .where(Project.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        projects_result = await db.execute(projects_stmt)
        projects = list(projects_result.scalars().all())
        
        if not projects:
            return {
                "total_projects": 0,
                "projects": [],
                "global_summary": {
                    "total_quoted": 0,
                    "total_invoiced": 0,
                    "total_paid": 0,
                    "total_overdue": 0,
                    "projects_with_overdue": 0,
                }
            }
        
        project_ids = [p.id for p in projects]
        
        # ═══════════════════════════════════════════════════════════
        # 2. Charger tous les DEVIS des projets
        # ═══════════════════════════════════════════════════════════
        quotes_stmt = (
            select(Document)
            .options(selectinload(Document.items))
            .where(
                Document.type == DocumentType.DEVIS,
                Document.project_id.in_(project_ids),
            )
        )
        quotes_result = await db.execute(quotes_stmt)
        all_quotes = list(quotes_result.scalars().all())
        
        # Map projet_id → devis_ids
        quote_ids_by_project = {}
        for q in all_quotes:
            pid = str(q.project_id)
            if pid not in quote_ids_by_project:
                quote_ids_by_project[pid] = []
            quote_ids_by_project[pid].append(q.id)
        
        all_quote_ids = [q.id for q in all_quotes]
        
        # ═══════════════════════════════════════════════════════════
        # 3. ✅ Charger les FACTURES :
        #    - soit liées au projet directement (project_id)
        #    - soit liées à un devis du projet (source_document_id)
        # ═══════════════════════════════════════════════════════════
        if all_quote_ids:
            invoices_stmt = (
                select(Document)
                .options(selectinload(Document.items))
                .where(
                    Document.type == DocumentType.FACTURE,
                    or_(
                        Document.project_id.in_(project_ids),
                        Document.source_document_id.in_(all_quote_ids),
                    )
                )
            )
        else:
            invoices_stmt = (
                select(Document)
                .options(selectinload(Document.items))
                .where(
                    Document.type == DocumentType.FACTURE,
                    Document.project_id.in_(project_ids),
                )
            )
        
        invoices_result = await db.execute(invoices_stmt)
        all_invoices = list(invoices_result.scalars().all())
        
        # ═══════════════════════════════════════════════════════════
        # 4. Agréger les stats par projet
        # ═══════════════════════════════════════════════════════════
        now = to_naive_utc(datetime.now(timezone.utc))
        today = now.date()
        
        project_stats = {
            str(pid): {
                "quote_count": 0,
                "accepted_quote_count": 0,
                "invoice_count": 0,
                "paid_invoice_count": 0,
                "overdue_invoice_count": 0,
                "total_quoted": 0,
                "total_invoiced": 0,
                "total_paid": 0,
                "total_overdue": 0,
            }
            for pid in project_ids
        }
        
        # Stats devis
        for quote in all_quotes:
            pid = str(quote.project_id)
            if pid not in project_stats:
                continue
            
            stats = project_stats[pid]
            quote_totals = DocumentService.calculate_totals(quote.items)
            amount = quote_totals["grand_total_cents"]
            status = quote.status.value if hasattr(quote.status, 'value') else quote.status
            
            stats["quote_count"] += 1
            stats["total_quoted"] += amount
            if status == "ACCEPTED":
                stats["accepted_quote_count"] += 1
        
        # Stats factures
        for inv in all_invoices:
            # Déterminer à quel projet appartient cette facture
            project_id_for_invoice = None
            
            if inv.project_id and str(inv.project_id) in project_stats:
                project_id_for_invoice = str(inv.project_id)
            elif inv.source_document_id:
                # Chercher le devis parent et son projet
                for pid, qids in quote_ids_by_project.items():
                    if inv.source_document_id in qids:
                        project_id_for_invoice = pid
                        break
            
            if not project_id_for_invoice:
                continue
            
            stats = project_stats[project_id_for_invoice]
            inv_totals = DocumentService.calculate_totals(inv.items)
            amount = inv_totals["grand_total_cents"]
            status = inv.status.value if hasattr(inv.status, 'value') else inv.status
            
            stats["invoice_count"] += 1
            stats["total_invoiced"] += amount
            
            is_actually_overdue = False
            if status == "OVERDUE":
                is_actually_overdue = True
            elif status in ["SENT", "VIEWED"] and inv.due_date and inv.due_date.date() < today:
                is_actually_overdue = True
            
            if status == "PAID":
                stats["paid_invoice_count"] += 1
                stats["total_paid"] += amount
            elif is_actually_overdue:
                stats["overdue_invoice_count"] += 1
                stats["total_overdue"] += amount
        
        # ═══════════════════════════════════════════════════════════
        # 5. Construire la réponse
        # ═══════════════════════════════════════════════════════════
        projects_data = []
        global_quoted = 0
        global_invoiced = 0
        global_paid = 0
        global_overdue = 0
        projects_with_overdue = 0
        fully_paid_count = 0
        
        for project in projects:
            pid = str(project.id)
            stats = project_stats[pid]
            
            invoicing_rate = round(
                (stats["total_invoiced"] / stats["total_quoted"] * 100), 1
            ) if stats["total_quoted"] > 0 else 0.0
            
            collection_rate = round(
                (stats["total_paid"] / stats["total_invoiced"] * 100), 1
            ) if stats["total_invoiced"] > 0 else 0.0
            
            has_overdue = stats["overdue_invoice_count"] > 0
            is_fully_paid = (
                stats["invoice_count"] > 0 and 
                stats["paid_invoice_count"] == stats["invoice_count"]
            )
            
            projects_data.append({
                "id": project.id,
                "name": project.name,
                "description": getattr(project, 'description', None),
                "created_at": project.created_at,
                "client_id": project.client_id,
                "client_name": project.client.name if project.client else None,
                "has_overdue": has_overdue,
                "is_fully_paid": is_fully_paid,
                "stats": {
                    **stats,
                    "invoicing_rate": invoicing_rate,
                    "collection_rate": collection_rate,
                }
            })
            
            global_quoted += stats["total_quoted"]
            global_invoiced += stats["total_invoiced"]
            global_paid += stats["total_paid"]
            global_overdue += stats["total_overdue"]
            if has_overdue:
                projects_with_overdue += 1
            if is_fully_paid:
                fully_paid_count += 1
        
        global_summary = {
            "total_quoted": global_quoted,
            "total_invoiced": global_invoiced,
            "total_paid": global_paid,
            "total_overdue": global_overdue,
            "projects_with_overdue": projects_with_overdue,
            "fully_paid_projects_count": fully_paid_count,
            "global_invoicing_rate": round(
                (global_invoiced / global_quoted * 100), 1
            ) if global_quoted > 0 else 0.0,
            "global_collection_rate": round(
                (global_paid / global_invoiced * 100), 1
            ) if global_invoiced > 0 else 0.0,
        }
        
        return {
            "total_projects": len(projects),
            "projects": projects_data,
            "global_summary": global_summary,
        }

    @staticmethod
    async def create_project(
        db: AsyncSession,
        user_id: UUID,
        client_id: UUID,
        name: str,
        description: Optional[str] = None,
        status: str = "DRAFT",
        budget_cents: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Project:
        """Crée un nouveau projet."""
        client = await db.execute(
            select(Client).where(
                Client.id == client_id,
                Client.user_id == user_id
            )
        )
        if not client.scalar_one_or_none():
            raise ValueError("Client introuvable ou n'appartient pas à cet utilisateur")
        
        project = Project(
            name=name,
            description=description,
            status=status,
            budget_cents=budget_cents,
            start_date=start_date,
            end_date=end_date,
            user_id=user_id,
            client_id=client_id,
        )
        db.add(project)
        await db.flush()
        
        result = await db.execute(
            select(Project)
            .options(
                selectinload(Project.attachments),
                selectinload(Project.documents)
            )
            .where(Project.id == project.id)
        )
        project_with_relations = result.scalar_one()
        
        logger.info(f"✅ Projet créé: {project.id} - {project.name}")
        return project_with_relations
    
    @staticmethod
    async def get_by_id(db: AsyncSession, project_id: UUID, user_id: UUID) -> Optional[Project]:
        """Récupère un projet avec ses relations."""
        result = await db.execute(
            select(Project)
            .options(
                selectinload(Project.attachments),
                selectinload(Project.documents),
                selectinload(Project.client)
            )
            .where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_project_tree(
        db: AsyncSession, 
        project_id: UUID, 
        user_id: UUID
    ) -> dict:
        """
        Retourne l'arborescence complète d'un projet.
        ✅ CORRIGÉ : charge les factures via source_document_id en plus de project_id
        """
        now = to_naive_utc(datetime.now(timezone.utc))
        today = now.date()
        
        # ═══════════════════════════════════════════════════════════
        # 1. Charger le projet avec le client
        # ═══════════════════════════════════════════════════════════
        project_stmt = (
            select(Project)
            .options(selectinload(Project.client))
            .where(Project.id == project_id, Project.user_id == user_id)
        )
        project_result = await db.execute(project_stmt)
        project = project_result.scalar_one_or_none()
        
        if not project:
            raise ValueError("Projet introuvable")
        
        # ═══════════════════════════════════════════════════════════
        # 2. Charger d'abord les DEVIS du projet
        # ═══════════════════════════════════════════════════════════
        quotes_stmt = (
            select(Document)
            .options(
                selectinload(Document.items),
                selectinload(Document.payment_schedule),
            )
            .where(
                Document.project_id == project_id,
                Document.type == DocumentType.DEVIS,
            )
            .order_by(Document.created_at.desc())
        )
        quotes_result = await db.execute(quotes_stmt)
        quotes = list(quotes_result.scalars().all())
        
        quote_ids = [q.id for q in quotes]
        
        # ═══════════════════════════════════════════════════════════
        # 3. ✅ Charger les FACTURES (par project_id OU source_document_id)
        # ═══════════════════════════════════════════════════════════
        if quote_ids:
            invoices_stmt = (
                select(Document)
                .options(selectinload(Document.items))
                .where(
                    Document.type == DocumentType.FACTURE,
                    or_(
                        Document.project_id == project_id,
                        Document.source_document_id.in_(quote_ids),
                    )
                )
                .order_by(Document.created_at.asc())
            )
        else:
            invoices_stmt = (
                select(Document)
                .options(selectinload(Document.items))
                .where(
                    Document.type == DocumentType.FACTURE,
                    Document.project_id == project_id,
                )
            )
        
        invoices_result = await db.execute(invoices_stmt)
        invoices = list(invoices_result.scalars().all())
        
        logger.info(f"🔍 Projet {project_id}: {len(quotes)} devis, {len(invoices)} factures trouvées")
        
        # ═══════════════════════════════════════════════════════════
        # 4. Indexer les factures par source_document_id
        # ═══════════════════════════════════════════════════════════
        invoices_by_source = {}
        standalone_invoices = []
        
        quote_ids_str = [str(qid) for qid in quote_ids]
        
        for inv in invoices:
            if inv.source_document_id and str(inv.source_document_id) in quote_ids_str:
                source_id = str(inv.source_document_id)
                if source_id not in invoices_by_source:
                    invoices_by_source[source_id] = []
                invoices_by_source[source_id].append(inv)
            else:
                # Facture sans devis parent (standalone)
                # Mais seulement si elle n'est pas déjà liée à un devis d'un autre projet
                standalone_invoices.append(inv)
        
        logger.info(f"📊 Indexation: {len(invoices_by_source)} devis avec factures, {len(standalone_invoices)} standalone")
        
        # ═══════════════════════════════════════════════════════════
        # 5. Construire la liste des devis avec leurs factures
        # ═══════════════════════════════════════════════════════════
        quotes_data = []
        
        total_quoted = 0
        total_invoiced = 0
        total_paid = 0
        total_overdue = 0
        total_pending = 0
        invoice_count = 0
        paid_invoice_count = 0
        overdue_invoice_count = 0
        
        for quote in quotes:
            quote_totals = DocumentService.calculate_totals(quote.items)
            quote_amount = quote_totals["grand_total_cents"]
            total_quoted += quote_amount
            
            # Milestones
            milestones_data = []
            for ms in sorted(quote.payment_schedule or [], key=lambda x: x.sequence):
                milestones_data.append({
                    "id": ms.id,
                    "sequence": ms.sequence,
                    "title": ms.title,
                    "percent": ms.percent,
                    "amount_cents": ms.amount_cents,
                    "description": ms.description,
                    "trigger_date": ms.trigger_date,
                    "status": ms.status.value if hasattr(ms.status, 'value') else ms.status,
                    "invoice_id": ms.invoice_id,
                })
            
            # Factures liées à ce devis
            quote_invoices = invoices_by_source.get(str(quote.id), [])
            invoices_data = []
            
            quote_invoiced = 0
            quote_paid = 0
            quote_overdue = 0
            
            for inv in quote_invoices:
                inv_totals = DocumentService.calculate_totals(inv.items)
                inv_amount = inv_totals["grand_total_cents"]
                
                inv_status = inv.status.value if hasattr(inv.status, 'value') else inv.status
                
                days_late = None
                if inv_status == "OVERDUE" and inv.due_date:
                    days_late = (today - inv.due_date.date()).days
                elif inv_status in ["SENT", "VIEWED"] and inv.due_date and inv.due_date.date() < today:
                    days_late = (today - inv.due_date.date()).days
                
                # Trouver le milestone lié
                milestone_id = None
                milestone_title = None
                for ms in (quote.payment_schedule or []):
                    if ms.invoice_id == inv.id:
                        milestone_id = ms.id
                        milestone_title = ms.title
                        break
                
                invoices_data.append({
                    "id": inv.id,
                    "number": inv.number,
                    "invoice_type": inv.invoice_type.value if inv.invoice_type and hasattr(inv.invoice_type, 'value') else inv.invoice_type,
                    "status": inv_status,
                    "due_date": inv.due_date,
                    "issued_at": inv.created_at,
                    "amount_cents": inv_amount,
                    "milestone_id": milestone_id,
                    "milestone_title": milestone_title,
                    "days_late": days_late,
                })
                
                quote_invoiced += inv_amount
                invoice_count += 1
                
                if inv_status == "PAID":
                    quote_paid += inv_amount
                    paid_invoice_count += 1
                elif inv_status == "OVERDUE" or (days_late and days_late > 0):
                    quote_overdue += inv_amount
                    overdue_invoice_count += 1
            
            quote_pending = max(0, quote_amount - quote_invoiced)
            quote_summary = {
                "quoted_amount": quote_amount,
                "invoiced_amount": quote_invoiced,
                "paid_amount": quote_paid,
                "overdue_amount": quote_overdue,
                "pending_amount": quote_pending,
            }
            
            total_invoiced += quote_invoiced
            total_paid += quote_paid
            total_overdue += quote_overdue
            total_pending += quote_pending
            
            quotes_data.append({
                "id": quote.id,
                "number": quote.number,
                "status": quote.status.value if hasattr(quote.status, 'value') else quote.status,
                "created_at": quote.created_at,
                "accepted_at": quote.accepted_at,
                "amount_cents": quote_amount,
                "milestones": milestones_data,
                "invoices": invoices_data,
                "summary": quote_summary,
            })
        
        # ═══════════════════════════════════════════════════════════
        # 6. Factures standalone
        # ═══════════════════════════════════════════════════════════
        standalone_data = []
        for inv in standalone_invoices:
            inv_totals = DocumentService.calculate_totals(inv.items)
            inv_amount = inv_totals["grand_total_cents"]
            inv_status = inv.status.value if hasattr(inv.status, 'value') else inv.status
            
            days_late = None
            if inv_status == "OVERDUE" and inv.due_date:
                days_late = (today - inv.due_date.date()).days
            
            standalone_data.append({
                "id": inv.id,
                "number": inv.number,
                "status": inv_status,
                "due_date": inv.due_date,
                "amount_cents": inv_amount,
                "days_late": days_late,
            })
            
            total_invoiced += inv_amount
            invoice_count += 1
            if inv_status == "PAID":
                total_paid += inv_amount
                paid_invoice_count += 1
            elif inv_status == "OVERDUE":
                total_overdue += inv_amount
                overdue_invoice_count += 1
        
        # ═══════════════════════════════════════════════════════════
        # 7. Résumé projet agrégé
        # ═══════════════════════════════════════════════════════════
        invoicing_rate = round((total_invoiced / total_quoted * 100), 1) if total_quoted > 0 else 0.0
        collection_rate = round((total_paid / total_invoiced * 100), 1) if total_invoiced > 0 else 0.0
        
        project_summary = {
            "total_quoted": total_quoted,
            "total_invoiced": total_invoiced,
            "total_paid": total_paid,
            "total_overdue": total_overdue,
            "total_pending": total_pending,
            "quote_count": len(quotes),
            "invoice_count": invoice_count,
            "paid_invoice_count": paid_invoice_count,
            "overdue_invoice_count": overdue_invoice_count,
            "invoicing_rate": invoicing_rate,
            "collection_rate": collection_rate,
        }
        
        return {
            "project_id": project.id,
            "project_name": project.name,
            "client_id": project.client_id,
            "client_name": project.client.name if project.client else None,
            "quotes": quotes_data,
            "standalone_invoices": standalone_data,
            "summary": project_summary,
        }

    @staticmethod
    async def get_all(
        db: AsyncSession,
        user_id: UUID,
        status: Optional[str] = None,
        client_id: Optional[UUID] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Project]:
        """Liste les projets avec filtres."""
        query = select(Project).where(Project.user_id == user_id)
        
        if status:
            query = query.where(Project.status == status)
        if client_id:
            query = query.where(Project.client_id == client_id)
        if search:
            query = query.where(Project.name.ilike(f"%{search}%"))
        
        query = query.order_by(Project.created_at.desc()).offset(skip).limit(limit)
        
        result = await db.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def update_project(
        db: AsyncSession,
        project: Project,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        budget_cents: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        client_id: Optional[UUID] = None,
    ) -> Project:
        """Met à jour un projet."""
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if status is not None:
            project.status = status
        if budget_cents is not None:
            project.budget_cents = budget_cents
        if start_date is not None:
            project.start_date = start_date
        if end_date is not None:
            project.end_date = end_date
        if client_id is not None:
            client = await db.execute(
                select(Client).where(
                    Client.id == client_id,
                    Client.user_id == project.user_id
                )
            )
            if not client.scalar_one_or_none():
                raise ValueError("Client introuvable ou n'appartient pas à cet utilisateur")
            project.client_id = client_id
        
        db.add(project)
        await db.flush()
        await db.refresh(project)
        
        logger.info(f"✅ Projet mis à jour: {project.id}")
        return project
    
    @staticmethod
    async def delete_project(db: AsyncSession, project: Project) -> None:
        """Supprime un projet et ses attachments."""
        for attachment in project.attachments:
            await db.delete(attachment)
        await db.flush()
        
        await db.delete(project)
        await db.commit()
        
        logger.info(f"✅ Projet supprimé: {project.id}")
    
    @staticmethod
    async def get_project_stats(db: AsyncSession, project_id: UUID, user_id: UUID) -> dict:
        """Calcule les statistiques d'un projet."""
        docs_count = await db.execute(
            select(func.count(Document.id)).where(
                Document.project_id == project_id,
                Document.user_id == user_id
            )
        )
        documents_count = docs_count.scalar() or 0
        
        total_result = await db.execute(
            select(
                func.sum(
                    DocumentItem.quantity * DocumentItem.unit_price_cents + 
                    (DocumentItem.quantity * DocumentItem.unit_price_cents * DocumentItem.tax_rate / 100)
                )
            )
            .join(Document, DocumentItem.document_id == Document.id)
            .where(
                Document.project_id == project_id,
                Document.user_id == user_id,
                Document.type == DocumentType.FACTURE,
                Document.status.in_(["PAID", "SENT", "VIEWED"])
            )
        )
        total_invoiced_cents = total_result.scalar() or 0
        
        return {
            "documents_count": documents_count,
            "total_invoiced_cents": int(total_invoiced_cents),
        }
    
    @staticmethod
    async def add_attachment(
        db: AsyncSession,
        project_id: UUID,
        user_id: UUID,
        name: str,
        file_url: str,
        file_type: str = "OTHER",
    ) -> ProjectAttachment:
        """Ajoute un attachment à un projet."""
        project = await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            )
        )
        if not project.scalar_one_or_none():
            raise ValueError("Projet introuvable")
        
        attachment = ProjectAttachment(
            name=name,
            file_url=file_url,
            file_type=file_type,
            project_id=project_id,
            user_id=user_id,
        )
        db.add(attachment)
        await db.flush()
        await db.refresh(attachment)
        
        logger.info(f"✅ Attachment ajouté: {attachment.id} au projet {project_id}")
        return attachment
    
    @staticmethod
    async def delete_attachment(db: AsyncSession, attachment_id: UUID, user_id: UUID) -> None:
        """Supprime un attachment."""
        result = await db.execute(
            select(ProjectAttachment).where(
                ProjectAttachment.id == attachment_id,
                ProjectAttachment.user_id == user_id
            )
        )
        attachment = result.scalar_one_or_none()
        
        if not attachment:
            raise ValueError("Attachment introuvable")
        
        await db.delete(attachment)
        await db.commit()
        
        logger.info(f"✅ Attachment supprimé: {attachment_id}")