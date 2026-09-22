"""Add color, category, region, grape to products.

Revision ID: 20260922_0005
Revises: 20260918_0004
Create Date: 2026-09-22 09:30:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "20260922_0005"
down_revision = "20260918_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("color", sa.String(length=200), nullable=True))
    op.add_column("products", sa.Column("category", sa.String(length=200), nullable=True))
    op.add_column("products", sa.Column("region", sa.String(length=300), nullable=True))
    op.add_column("products", sa.Column("grape", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "grape")
    op.drop_column("products", "region")
    op.drop_column("products", "category")
    op.drop_column("products", "color")
