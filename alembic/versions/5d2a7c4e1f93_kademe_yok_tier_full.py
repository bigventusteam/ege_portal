"""kademe yok: plan_items.tier = 'full'

Kullanıcı kararı (2026-10-06): üç üründe de lisans = tam sürüm, kademe yok.
`tier` alanı imzalı şema v2 uyumluluğu için kalır; mevcut satırlar 'full'a
çevrilir (yalnız UPDATE, satır silinmez) ve yeni satırların varsayılanı 'full'.

Revision ID: 5d2a7c4e1f93
Revises: 3c8e1f0a9b47
Create Date: 2026-10-06 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d2a7c4e1f93'
down_revision: Union[str, None] = '3c8e1f0a9b47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE plan_items SET tier = 'full' WHERE tier <> 'full'"))
    with op.batch_alter_table('plan_items', schema=None) as batch_op:
        batch_op.alter_column('tier', existing_type=sa.String(length=30), existing_nullable=False, server_default='full')


def downgrade() -> None:
    # Eski kademe değerleri (pro/standard/lite) geri getirilemez — yalnız
    # varsayılan kaldırılır; satırlar 'full' kalır.
    with op.batch_alter_table('plan_items', schema=None) as batch_op:
        batch_op.alter_column('tier', existing_type=sa.String(length=30), existing_nullable=False, server_default=None)
