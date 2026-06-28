"""Scene-aware clip model: scenes table, mark scene columns, profile context ranges.

Revision ID: e1f3a9c72b40
Revises: d7c2e4a91b06
Create Date: 2026-06-20
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e1f3a9c72b40'
down_revision: str | Sequence[str] | None = 'd7c2e4a91b06'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'scenes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('clip_id', sa.String(), sa.ForeignKey('clips.id'), nullable=False),
        sa.Column('scene_index', sa.Integer(), nullable=False),
        sa.Column('start_s', sa.Float(), nullable=False),
        sa.Column('end_s', sa.Float(), nullable=False),
    )
    op.add_column('marks', sa.Column('normalised_score', sa.Float(), nullable=True))
    op.add_column('marks', sa.Column('scene_start', sa.Float(), nullable=True))
    op.add_column('marks', sa.Column('scene_end', sa.Float(), nullable=True))
    op.add_column('profiles', sa.Column('clip_pre_min_s', sa.Float(), nullable=True))
    op.add_column('profiles', sa.Column('clip_pre_max_s', sa.Float(), nullable=True))
    op.add_column('profiles', sa.Column('clip_post_min_s', sa.Float(), nullable=True))
    op.add_column('profiles', sa.Column('clip_post_max_s', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'clip_post_max_s')
    op.drop_column('profiles', 'clip_post_min_s')
    op.drop_column('profiles', 'clip_pre_max_s')
    op.drop_column('profiles', 'clip_pre_min_s')
    op.drop_column('marks', 'scene_end')
    op.drop_column('marks', 'scene_start')
    op.drop_column('marks', 'normalised_score')
    op.drop_table('scenes')
