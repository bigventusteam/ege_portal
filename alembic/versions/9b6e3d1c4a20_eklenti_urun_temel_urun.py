"""ek ürün (eklenti): products.requires_product_id

Bir ürün başka bir ürünün EKLENTİSİ olabilir (ör. colege_soru -> colege):
yalnız temel ürünün aktif aboneliği olan müşteriye satılır ve temel ürünün
aktivasyonuna (aynı kurulum, aynı license.json) eklenir. Bkz.
app/services/eklentiler.py. Mevcut satırlar NULL kalır (eklenti değil).

Revision ID: 9b6e3d1c4a20
Revises: 5d2a7c4e1f93
Create Date: 2026-10-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b6e3d1c4a20'
down_revision: Union[str, None] = '5d2a7c4e1f93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.add_column(sa.Column('requires_product_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_products_requires_product_id_products', 'products', ['requires_product_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('products', schema=None) as batch_op:
        batch_op.drop_constraint('fk_products_requires_product_id_products', type_='foreignkey')
        batch_op.drop_column('requires_product_id')
