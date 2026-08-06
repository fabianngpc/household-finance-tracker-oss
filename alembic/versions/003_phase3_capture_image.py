"""phase 3 capture image_path column

Revision ID: 003_phase3_capture_image
Revises: 002_telegram_phase2
Create Date: 2026-06-29 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "003_phase3_capture_image"
down_revision = "002_telegram_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add image_path column to captures table."""
    op.add_column("captures", sa.Column("image_path", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove image_path column from captures table."""
    op.drop_column("captures", "image_path")
