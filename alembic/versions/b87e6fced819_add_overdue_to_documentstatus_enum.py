"""add_overdue_to_documentstatus_enum

Revision ID: <garde-l-id-genere>
Revises: 4dc093cdf101  # ← ta dernière migration
Create Date: 2026-08-17
"""
from typing import Sequence, Union
from alembic import op


revision: str = 'b87e6fced819'
down_revision: Union[str, Sequence[str], None] = '1b8172fc1f41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute la valeur OVERDUE à l'ENUM documentstatus."""
    # PostgreSQL : ALTER TYPE documentstatus ADD VALUE 'OVERDUE'
    # IF NOT EXISTS évite l'erreur si déjà présent (idempotent)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum 
                WHERE enumlabel = 'OVERDUE' 
                AND enumtypid = 'documentstatus'::regtype
            ) THEN
                ALTER TYPE documentstatus ADD VALUE 'OVERDUE';
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    """
    PostgreSQL ne supporte pas nativement la suppression d'une valeur ENUM.
    On laisse OVERDUE en place en downgrade (pas de problème).
    Si vraiment nécessaire, il faudrait recréer le type complet.
    """
    pass