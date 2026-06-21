"""add scene detection params to profiles

Revision ID: a3c91f2d0e47
Revises: 31bd52c385c9
Create Date: 2026-06-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3c91f2d0e47'
down_revision: Union[str, Sequence[str], None] = '31bd52c385c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('scene_detector', sa.String(), nullable=False, server_default='content'))
    op.add_column('profiles', sa.Column('scene_threshold', sa.Float(), nullable=True))
    op.add_column('profiles', sa.Column('scene_min_scene_len', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'scene_min_scene_len')
    op.drop_column('profiles', 'scene_threshold')
    op.drop_column('profiles', 'scene_detector')
