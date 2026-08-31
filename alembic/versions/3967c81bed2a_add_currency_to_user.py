"""add_currency_to_user

Revision ID: 3967c81bed2a
Revises: b87e6fced819
Create Date: 2026-08-28 19:14:16.133704

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3967c81bed2a'
down_revision: Union[str, Sequence[str], None] = 'b87e6fced819'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("country", sa.String(), nullable=True))
    op.add_column("user", sa.Column("currency", sa.String(), nullable=False, server_default="XOF"))

def downgrade() -> None:
    op.drop_column("user", "currency")
    op.drop_column("user", "country")
