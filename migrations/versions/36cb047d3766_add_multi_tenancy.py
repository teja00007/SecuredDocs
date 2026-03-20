"""add_multi_tenancy

Revision ID: 36cb047d3766
Revises:
Create Date: 2026-03-17 04:30:04.085099

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36cb047d3766'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. companies table (skip if already exists from partial prior run) ──
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'companies' not in existing_tables:
        op.create_table('companies',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('slug', sa.String(length=100), nullable=False),
            sa.Column('license_key', sa.String(length=50), nullable=True),
            sa.Column('plan', sa.String(length=50), nullable=False),
            sa.Column('max_users', sa.Integer(), nullable=False),
            sa.Column('max_storage_gb', sa.Integer(), nullable=False),
            sa.Column('billing_cycle', sa.String(length=20), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('owner_email', sa.String(length=255), nullable=True),
            sa.Column('logo_url', sa.String(length=500), nullable=True),
            sa.Column('brand_color', sa.String(length=20), nullable=True),
            sa.Column('custom_domain', sa.String(length=255), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_companies_owner_email', 'companies', ['owner_email'], unique=False)
        op.create_index('ix_companies_slug', 'companies', ['slug'], unique=True)

    # ── 2. collections: add company_id ──
    cols = {c['name'] for c in inspector.get_columns('collections')}
    if 'company_id' not in cols:
        with op.batch_alter_table('collections', schema=None) as batch_op:
            batch_op.add_column(sa.Column('company_id', sa.String(length=36), nullable=True))
            batch_op.create_index('ix_collections_company_id', ['company_id'], unique=False)
            batch_op.create_foreign_key('fk_collections_company_id', 'companies', ['company_id'], ['id'], ondelete='CASCADE')

    # ── 3. teams: add company_id, make name non-unique globally ──
    cols = {c['name'] for c in inspector.get_columns('teams')}
    if 'company_id' not in cols:
        with op.batch_alter_table('teams', schema=None) as batch_op:
            batch_op.add_column(sa.Column('company_id', sa.String(length=36), nullable=True))
            # Drop old unique index, recreate as non-unique
            batch_op.drop_index('ix_teams_name')
            batch_op.create_index('ix_teams_name', ['name'], unique=False)
            batch_op.create_index('ix_teams_company_id', ['company_id'], unique=False)
            batch_op.create_foreign_key('fk_teams_company_id', 'companies', ['company_id'], ['id'], ondelete='CASCADE')

    # ── 4. users: add company_id + is_super_admin ──
    cols = {c['name'] for c in inspector.get_columns('users')}
    if 'company_id' not in cols or 'is_super_admin' not in cols:
        with op.batch_alter_table('users', schema=None) as batch_op:
            if 'email_verified' not in cols:
                batch_op.add_column(sa.Column('email_verified', sa.Boolean(), nullable=True))
            if 'email_verification_token' not in cols:
                batch_op.add_column(sa.Column('email_verification_token', sa.String(length=64), nullable=True))
                batch_op.create_index('ix_users_email_verification_token', ['email_verification_token'], unique=False)
            if 'company_id' not in cols:
                batch_op.add_column(sa.Column('company_id', sa.String(length=36), nullable=True))
                batch_op.create_index('ix_users_company_id', ['company_id'], unique=False)
                batch_op.create_foreign_key('fk_users_company_id', 'companies', ['company_id'], ['id'], ondelete='SET NULL')
            if 'is_super_admin' not in cols:
                # server_default='0' so existing rows get False without violating NOT NULL
                batch_op.add_column(sa.Column('is_super_admin', sa.Boolean(), nullable=False, server_default='0'))
            if 'password_reset_token' in cols:
                # Add index if missing
                existing_idx = {i['name'] for i in inspector.get_indexes('users')}
                if 'ix_users_password_reset_token' not in existing_idx:
                    batch_op.create_index('ix_users_password_reset_token', ['password_reset_token'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_company_id', type_='foreignkey')
        batch_op.drop_index('ix_users_company_id')
        batch_op.drop_column('is_super_admin')
        batch_op.drop_column('company_id')

    with op.batch_alter_table('teams', schema=None) as batch_op:
        batch_op.drop_constraint('fk_teams_company_id', type_='foreignkey')
        batch_op.drop_index('ix_teams_company_id')
        batch_op.drop_index('ix_teams_name')
        batch_op.create_index('ix_teams_name', ['name'], unique=True)
        batch_op.drop_column('company_id')

    with op.batch_alter_table('collections', schema=None) as batch_op:
        batch_op.drop_constraint('fk_collections_company_id', type_='foreignkey')
        batch_op.drop_index('ix_collections_company_id')
        batch_op.drop_column('company_id')

    op.drop_index('ix_companies_slug', table_name='companies')
    op.drop_index('ix_companies_owner_email', table_name='companies')
    op.drop_table('companies')
