"""telegram phase 2 schema

Revision ID: 002_telegram_phase2
Revises: f298a10e2cc8
Create Date: 2026-06-29 04:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_telegram_phase2'
down_revision = 'f298a10e2cc8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add Telegram-link columns to users
    op.add_column('users', sa.Column('telegram_id', sa.BigInteger(), nullable=True))
    op.add_column('users', sa.Column('link_code', sa.String(), nullable=True))
    op.add_column('users', sa.Column('link_code_expires_at', sa.DateTime(), nullable=True))
    op.create_index('ix_users_telegram_id', 'users', ['telegram_id'], unique=True)
    op.create_index('ix_users_link_code', 'users', ['link_code'], unique=True)

    # Create captures table
    op.create_table('captures',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('update_id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_chat_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('raw_message', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('confirm_step', sa.String(), nullable=True),
        sa.Column('amount_str', sa.String(), nullable=True),
        sa.Column('currency', sa.String(), nullable=True),
        sa.Column('merchant', sa.String(), nullable=True),
        sa.Column('expense_date', sa.String(), nullable=True),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('expense_id', sa.Integer(), nullable=True),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id']),
        sa.ForeignKeyConstraint(['expense_id'], ['expenses.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('update_id'),
    )
    op.create_index('idx_captures_telegram_user_status', 'captures', ['telegram_user_id', 'status'])

    # Create jobs table
    op.create_table('jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('capture_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['capture_id'], ['captures.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_jobs_status_created', 'jobs', ['status', 'created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop jobs and captures tables
    op.drop_index('idx_jobs_status_created', table_name='jobs')
    op.drop_table('jobs')
    op.drop_index('idx_captures_telegram_user_status', table_name='captures')
    op.drop_table('captures')

    # Drop users Telegram indexes and columns using batch for SQLite compatibility
    op.drop_index('ix_users_telegram_id', table_name='users')
    op.drop_index('ix_users_link_code', table_name='users')
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('link_code_expires_at')
        batch_op.drop_column('link_code')
        batch_op.drop_column('telegram_id')
