"""share token to document

Revision ID: 9c57d82ac368
Revises: add_projects_001
Create Date: 2026-07-07 00:56:50.679155

"""
from typing import Sequence, Union
import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c57d82ac368'
down_revision: Union[str, Sequence[str], None] = 'add_projects_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('document', sa.Column('share_token', sa.String(length=64), nullable=True))
    op.add_column('document', sa.Column('share_enabled', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('document', sa.Column('share_expires_at', sa.DateTime(), nullable=True))
    
    # Index unique sur share_token
    op.create_index('ix_document_share_token', 'document', ['share_token'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_document_share_token', table_name='document')
    op.drop_column('document', 'share_expires_at')
    op.drop_column('document', 'share_enabled')
    op.drop_column('document', 'share_token')
