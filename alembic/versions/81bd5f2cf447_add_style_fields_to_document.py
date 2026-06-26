"""add style fields to document

Revision ID: 81bd5f2cf447
Revises: b05e400d0318
Create Date: 2026-06-26 01:36:00.173186

"""
from typing import Sequence, Union
import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '81bd5f2cf447'
down_revision: Union[str, Sequence[str], None] = 'b05e400d0318'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # ✅ Couleurs (string, nullable)
    op.add_column('document', sa.Column('primary_color', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('document', sa.Column('secondary_color', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('document', sa.Column('accent_color', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('document', sa.Column('background_color', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('document', sa.Column('text_color', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.add_column('document', sa.Column('font_family', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    
    # ✅ Booléens avec server_default pour les lignes existantes
    op.add_column(
        'document', 
        sa.Column(
            'show_bank_details', 
            sa.Boolean(), 
            nullable=False,
            server_default=sa.text('true')  # ← Valeur par défaut pour les lignes existantes
        )
    )
    op.add_column(
        'document', 
        sa.Column(
            'show_tax_id', 
            sa.Boolean(), 
            nullable=False,
            server_default=sa.text('true')  # ← Valeur par défaut pour les lignes existantes
        )
    )
    
    # ✅ Mettre à jour les lignes existantes avec les valeurs par défaut des couleurs
    op.execute("""
        UPDATE document 
        SET 
            primary_color = '#2563EB',
            secondary_color = '#1E40AF',
            accent_color = '#DBEAFE',
            background_color = '#FFFFFF',
            text_color = '#1F2937',
            font_family = 'Inter'
        WHERE primary_color IS NULL
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('document', 'show_tax_id')
    op.drop_column('document', 'show_bank_details')
    op.drop_column('document', 'font_family')
    op.drop_column('document', 'text_color')
    op.drop_column('document', 'background_color')
    op.drop_column('document', 'accent_color')
    op.drop_column('document', 'secondary_color')
    op.drop_column('document', 'primary_color')