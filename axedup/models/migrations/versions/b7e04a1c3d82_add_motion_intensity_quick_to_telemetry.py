"""add motion_intensity_quick to telemetry

Revision ID: b7e04a1c3d82
Revises: a3c91f2d0e47
Create Date: 2026-06-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e04a1c3d82'
down_revision: Union[str, Sequence[str], None] = 'a3c91f2d0e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('telemetry', sa.Column('motion_intensity_quick', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('telemetry', 'motion_intensity_quick')
