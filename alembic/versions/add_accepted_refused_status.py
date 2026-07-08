# alembic/versions/add_accepted_refused_status.py

"""add accepted refused status

Revision ID: add_status_001
Revises: 3709db93c332
Create Date: 2026-07-08 18:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'add_status_001'
down_revision: Union[str, None] = '3709db93c332'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute les valeurs ACCEPTED et REFUSED à l'enum et les colonnes de validation."""
    
    # 1. Ajouter les nouvelles valeurs à l'enum PostgreSQL
    op.execute("ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS 'ACCEPTED'")
    op.execute("ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS 'REFUSED'")
    
    # 2. Vérifier quelles colonnes existent déjà
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('document')]
    
    # 3. Ajouter les colonnes manquantes une par une
    if 'accepted_at' not in columns:
        op.add_column('document', sa.Column('accepted_at', sa.DateTime(), nullable=True))
    
    if 'refused_at' not in columns:
        op.add_column('document', sa.Column('refused_at', sa.DateTime(), nullable=True))
    
    if 'refusal_reason' not in columns:
        op.add_column('document', sa.Column('refusal_reason', sa.Text(), nullable=True))
    
    if 'signature_name' not in columns:
        op.add_column('document', sa.Column('signature_name', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Retire les champs de validation."""
    op.drop_column('document', 'signature_name')
    op.drop_column('document', 'refusal_reason')
    op.drop_column('document', 'refused_at')
    op.drop_column('document', 'accepted_at')