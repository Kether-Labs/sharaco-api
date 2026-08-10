"""add_invoice_fields_and_billing_settings

Revision ID: [ID_GÉNÉRÉ]
Revises: 58386e7e1545
Create Date: 2026-08-10 ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '6e675a41d886'  # ← garde l'ID généré
down_revision: Union[str, Sequence[str], None] = '58386e7e1545'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # 1. Ajout des colonnes sur la table `document`
    # ============================================================
    # ✅ invoice_type en String (pas en Enum PostgreSQL)
    op.add_column('document', sa.Column(
        'invoice_type',
        sa.String(length=20),  # ← String simple
        nullable=True
    ))
    
    op.add_column('document', sa.Column(
        'source_document_id',
        sa.Uuid(),
        nullable=True
    ))
    
    op.add_column('document', sa.Column(
        'origin',
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        server_default='manual'
    ))
    
    op.create_index(
        op.f('ix_document_source_document_id'),
        'document', ['source_document_id'],
        unique=False
    )
    
    op.create_foreign_key(
        'fk_document_source_document_id',
        'document', 'document',
        ['source_document_id'], ['id']
    )

    # ============================================================
    # 2. Création de la table `billing_settings`
    # ============================================================
    op.create_table(
        'billing_settings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('auto_create_invoice', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('auto_send_invoice', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('acompte_percent', sa.Float(), nullable=True),
        sa.Column('invoice_prefix', sa.String(length=10), nullable=False, server_default='FACT'),
        sa.Column(
            'invoice_number_format',
            sa.String(),
            nullable=False,
            server_default='{prefix}-{year}-{seq:03d}'
        ),
        sa.Column('default_payment_terms_days', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('default_late_fee_percent', sa.Float(), nullable=False, server_default='1.5'),
        sa.Column('legal_mentions', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], name='fk_billing_settings_user_id'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_billing_settings_user_id'),
    )
    op.create_index(
        op.f('ix_billing_settings_user_id'),
        'billing_settings', ['user_id'],
        unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_billing_settings_user_id'), table_name='billing_settings')
    op.drop_table('billing_settings')

    op.drop_constraint('fk_document_source_document_id', 'document', type_='foreignkey')
    op.drop_index(op.f('ix_document_source_document_id'), table_name='document')
    op.drop_column('document', 'origin')
    op.drop_column('document', 'source_document_id')
    op.drop_column('document', 'invoice_type')