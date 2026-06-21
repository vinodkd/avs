"""add audio_energy to telemetry

Revision ID: d7c2e4a91b06
Revises: c4d18e9f5a23
Create Date: 2026-06-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7c2e4a91b06'
down_revision: Union[str, Sequence[str], None] = 'c4d18e9f5a23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('telemetry', sa.Column('audio_energy', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('telemetry', 'audio_energy')
