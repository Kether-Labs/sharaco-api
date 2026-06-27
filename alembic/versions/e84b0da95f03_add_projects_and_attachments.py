"""add projects and attachments

Revision ID: add_projects_001
Revises: 81bd5f2cf447
Create Date: 2026-06-27 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'add_projects_001'
down_revision: Union[str, None] = '81bd5f2cf447'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - Sans enums PostgreSQL."""
    
    # Créer la table 'project' avec des VARCHAR simples
    op.create_table(
        'project',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='DRAFT'),
        sa.Column('budget_cents', sa.Integer(), nullable=True),
        sa.Column('start_date', sa.DateTime(), nullable=True),
        sa.Column('end_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('client.id'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_project_user_id', 'project', ['user_id'])
    op.create_index('ix_project_client_id', 'project', ['client_id'])
    op.create_index('ix_project_status', 'project', ['status'])

    # Créer la table 'project_attachment'
    op.create_table(
        'project_attachment',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('file_url', sa.String(length=1000), nullable=False),
        sa.Column('file_type', sa.String(length=20), nullable=False, server_default='OTHER'),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('user.id'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_project_attachment_project_id', 'project_attachment', ['project_id'])

    # Ajouter 'project_id' à la table 'document'
    op.add_column(
        'document', 
        sa.Column(
            'project_id', 
            postgresql.UUID(as_uuid=True), 
            sa.ForeignKey('project.id', ondelete='SET NULL'), 
            nullable=True
        )
    )
    op.create_index('ix_document_project_id', 'document', ['project_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_document_project_id', table_name='document')
    op.drop_column('document', 'project_id')
    
    op.drop_index('ix_project_attachment_project_id', table_name='project_attachment')
    op.drop_table('project_attachment')
    
    op.drop_index('ix_project_status', table_name='project')
    op.drop_index('ix_project_client_id', table_name='project')
    op.drop_index('ix_project_user_id', table_name='project')
    op.drop_table('project')