from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.document_template import DocumentTemplate
from uuid import UUID
from typing import Optional


class TemplateService:
    @staticmethod
    async def create_template(
        db: AsyncSession,
        name: str,
        user_id: UUID,
        primary_color: str = "#2563EB",
        secondary_color: str = "#1E40AF",
        accent_color: str = "#DBEAFE",
        text_color: str = "#1F2937",
        background_color: str = "#FFFFFF",
        logo_url: Optional[str] = None,
        font_family: str = "Inter",
        header_text: Optional[str] = None,
        footer_text: Optional[str] = None,
        show_bank_details: bool = True,
        show_tax_id: bool = True,
        layout_style: str = "classic",
        is_default: bool = False,
    ) -> DocumentTemplate:
        # Si c'est le template par défaut, retirer le flag des autres
        if is_default:
            await TemplateService._unset_default(db, user_id)

        template = DocumentTemplate(
            name=name,
            user_id=user_id,
            primary_color=primary_color,
            secondary_color=secondary_color,
            accent_color=accent_color,
            text_color=text_color,
            background_color=background_color,
            logo_url=logo_url,
            font_family=font_family,
            header_text=header_text,
            footer_text=footer_text,
            show_bank_details=show_bank_details,
            show_tax_id=show_tax_id,
            layout_style=layout_style,
            is_default=is_default,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return template

    @staticmethod
    async def get_by_id(db: AsyncSession, template_id: UUID, user_id: UUID) -> DocumentTemplate | None:
        """Récupère un template par ID avec vérification d'appartenance."""
        statement = select(DocumentTemplate).where(
            DocumentTemplate.id == template_id,
            DocumentTemplate.user_id == user_id,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(db: AsyncSession, user_id: UUID) -> list[DocumentTemplate]:
        """Liste tous les templates d'un utilisateur."""
        statement = (
            select(DocumentTemplate)
            .where(DocumentTemplate.user_id == user_id)
            .order_by(DocumentTemplate.is_default.desc(), DocumentTemplate.name)
        )
        result = await db.execute(statement)
        return list(result.scalars().all())

    @staticmethod
    async def get_default(db: AsyncSession, user_id: UUID) -> DocumentTemplate | None:
        """Récupère le template par défaut d'un utilisateur."""
        statement = select(DocumentTemplate).where(
            DocumentTemplate.user_id == user_id,
            DocumentTemplate.is_default == True,
        )
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    @staticmethod
    async def update_template(db: AsyncSession, template: DocumentTemplate, **kwargs) -> DocumentTemplate:
        """Met à jour les champs fournis d'un template."""
        from datetime import datetime, timezone

        is_default = kwargs.get("is_default")
        if is_default:
            await TemplateService._unset_default(db, template.user_id)

        for key, value in kwargs.items():
            if value is not None and hasattr(template, key):
                setattr(template, key, value)

        template.updated_at = datetime.now(timezone.utc)
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return template

    @staticmethod
    async def delete_template(db: AsyncSession, template: DocumentTemplate) -> None:
        """Supprime un template."""
        await db.delete(template)
        await db.commit()

    @staticmethod
    async def _unset_default(db: AsyncSession, user_id: UUID) -> None:
        """Retire le flag is_default de tous les templates d'un utilisateur."""
        statement = select(DocumentTemplate).where(
            DocumentTemplate.user_id == user_id,
            DocumentTemplate.is_default == True,
        )
        result = await db.execute(statement)
        for tmpl in result.scalars().all():
            tmpl.is_default = False
            db.add(tmpl)
        await db.commit()
