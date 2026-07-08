# alembic/versions/add_accepted_refused_status.py
from alembic import op

import sqlalchemy as sa

def upgrade() -> None:
    # PostgreSQL : ajouter les nouvelles valeurs à l'enum
    op.execute("ALTER TYPE documentstatus ADD VALUE 'ACCEPTED'")
    op.execute("ALTER TYPE documentstatus ADD VALUE 'REFUSED'")
    
    # Ajouter les champs pour la validation
    op.add_column('document', sa.Column('accepted_at', sa.DateTime(), nullable=True))
    op.add_column('document', sa.Column('refused_at', sa.DateTime(), nullable=True))
    op.add_column('document', sa.Column('refusal_reason', sa.Text(), nullable=True))
    op.add_column('document', sa.Column('signature_name', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('document', 'signature_name')
    op.drop_column('document', 'refusal_reason')
    op.drop_column('document', 'refused_at')
    op.drop_column('document', 'accepted_at')