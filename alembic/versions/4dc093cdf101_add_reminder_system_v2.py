"""add_billing_and_payment_schedule

Revision ID: 4dc093cdf101
Revises: aecea1cafe60
Create Date: 2026-08-17 10:55:20.934615
"""
from typing import Sequence, Union
import sqlmodel
from alembic import op
import sqlalchemy as sa


revision: str = '4dc093cdf101'
down_revision: Union[str, Sequence[str], None] = 'aecea1cafe60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Ajoute billing_settings + payment_schedule + colonnes document.
    Les tables reminder existent déjà, on ne les touche PAS.
    L'ENUM milestonestatus existe déjà, on le réutilise.
    """
    
    # ═══════════════════════════════════════════════════════════════
    # 1. Table billing_settings (NOUVELLE)
    # ═══════════════════════════════════════════════════════════════
    op.create_table('billing_settings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('auto_create_invoice', sa.Boolean(), nullable=False),
        sa.Column('auto_send_invoice', sa.Boolean(), nullable=False),
        sa.Column('acompte_percent', sa.Float(), nullable=True),
        sa.Column('invoice_prefix', sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
        sa.Column('invoice_number_format', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('default_payment_terms_days', sa.Integer(), nullable=False),
        sa.Column('default_late_fee_percent', sa.Float(), nullable=False),
        sa.Column('legal_mentions', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_billing_settings_user_id'), 'billing_settings', ['user_id'], unique=True)
    
    # ═══════════════════════════════════════════════════════════════
    # 2. Table payment_schedule (NOUVELLE)
    #    Réutilise l'ENUM milestonestatus déjà existant
    # ═══════════════════════════════════════════════════════════════
    op.create_table('payment_schedule',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('document_id', sa.Uuid(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('percent', sa.Float(), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('trigger_date', sa.DateTime(), nullable=True),
        
        # ✅ CORRECTION : create_type=False pour ne pas recréer l'ENUM
        sa.Column('status', 
            sa.Enum('PENDING', 'INVOICED', 'PAID', 'CANCELLED',
                    name='milestonestatus',
                    create_type=False),  # ← CLÉ !
            nullable=False),
        
        sa.Column('invoice_id', sa.Uuid(), nullable=True),
        sa.Column('invoiced_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['document.id']),
        sa.ForeignKeyConstraint(['invoice_id'], ['document.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payment_schedule_document_id'), 'payment_schedule', ['document_id'], unique=False)
    op.create_index(op.f('ix_payment_schedule_invoice_id'), 'payment_schedule', ['invoice_id'], unique=False)
    
    # ═══════════════════════════════════════════════════════════════
    # 3. Nouvelles colonnes sur document
    # ═══════════════════════════════════════════════════════════════
    op.add_column('document', sa.Column('invoice_type', sqlmodel.sql.sqltypes.AutoString(),create_type=False, nullable=True))
    op.add_column('document', sa.Column('source_document_id', sa.Uuid(), nullable=True))
    op.add_column('document', sa.Column('origin', sqlmodel.sql.sqltypes.AutoString(), nullable=True))  # ✅ nullable=True pour éviter les erreurs
    op.add_column('document', sa.Column('paid_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_document_source_document_id'), 'document', ['source_document_id'], unique=False)
    op.create_foreign_key('fk_document_source_document', 'document', 'document', ['source_document_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    # Colonnes document
    op.drop_constraint('fk_document_source_document', 'document', type_='foreignkey')
    op.drop_index(op.f('ix_document_source_document_id'), table_name='document')
    op.drop_column('document', 'paid_at')
    op.drop_column('document', 'origin')
    op.drop_column('document', 'source_document_id')
    op.drop_column('document', 'invoice_type')
    
    # payment_schedule
    op.drop_index(op.f('ix_payment_schedule_invoice_id'), table_name='payment_schedule')
    op.drop_index(op.f('ix_payment_schedule_document_id'), table_name='payment_schedule')
    op.drop_table('payment_schedule')
    
    # billing_settings
    op.drop_index(op.f('ix_billing_settings_user_id'), table_name='billing_settings')
    op.drop_table('billing_settings')
    
    # On ne supprime PAS l'ENUM milestonestatus en downgrade