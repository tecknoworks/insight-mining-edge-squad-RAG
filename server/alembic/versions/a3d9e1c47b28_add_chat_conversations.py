"""add conversations and chat_messages tables

Revision ID: a3d9e1c47b28
Revises: f8c2a1b3d4e5
Create Date: 2026-09-07 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3d9e1c47b28'
down_revision: str | None = 'f8c2a1b3d4e5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('conversations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('dataset_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        op.f('ix_conversations_dataset_id'), 'conversations', ['dataset_id'], unique=False
    )
    op.create_table('chat_messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column(
        'role',
        sa.Enum('USER', 'ASSISTANT', name='chatrole', native_enum=False),
        nullable=False,
    ),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('citations', sa.JSON(), nullable=True),
    # `sequence` rather than ordering by `created_at`: the two messages of one
    # turn are written milliseconds apart and the timestamps tie, which would
    # replay them out of order.
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('conversation_id', 'sequence', name='uq_chat_messages_conversation_seq')
    )
    op.create_index(
        op.f('ix_chat_messages_conversation_id'),
        'chat_messages',
        ['conversation_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_chat_messages_conversation_id'), table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_index(op.f('ix_conversations_dataset_id'), table_name='conversations')
    op.drop_table('conversations')
