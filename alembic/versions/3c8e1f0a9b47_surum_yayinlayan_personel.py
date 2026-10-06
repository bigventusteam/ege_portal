"""surum yayinlayan personel (releases.created_by_user_id)

Revision ID: 3c8e1f0a9b47
Revises: ab7f5d3b2823
Create Date: 2026-10-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c8e1f0a9b47'
down_revision: Union[str, None] = 'ab7f5d3b2823'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Önceden yayınlanmış satırlar için boş kalır (nullable).
    with op.batch_alter_table('releases', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by_user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_releases_created_by_user_id_users', 'users', ['created_by_user_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('releases', schema=None) as batch_op:
        batch_op.drop_constraint('fk_releases_created_by_user_id_users', type_='foreignkey')
        batch_op.drop_column('created_by_user_id')
