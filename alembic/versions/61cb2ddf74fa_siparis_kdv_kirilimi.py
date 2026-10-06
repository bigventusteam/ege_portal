"""siparis kdv kirilimi

Revision ID: 61cb2ddf74fa
Revises: a2e20db52f70
Create Date: 2026-10-05 10:18:23.212464

KARAR (2026-09-28, müşteri testinde bulundu — bkz. PLAN.md §8 madde 1):
`Price.amount` (ve dolayısıyla `Order.unit_price`) KDV HARİÇ net tutardır;
`total` artık `net + vat_amount` (KDV DAHİL). `unit_price` → `net`'e elle
YENİDEN ADLANDIRILDI (autogenerate bunu DROP+ADD olarak algılıyor — VERİ
KAYBI olurdu; değer zaten "o anki Price.amount" anlamına geliyordu, yalnız
sütun adı/anlamı netleşiyor, taşınacak bir veri yok).

`vat_amount` yeni bir sütun — var olan satırlar için `server_default='0.00'`
(fiyatlar henüz müşteride DEĞİL, bkz. görev notu; gerçek müşteri siparişi
olsaydı bu satır elle gözden geçirilmeden küçümsenmemeliydi). `total`
var olan satırlarda ELLE DOKUNULMADI — eski semantiğiyle tutarlı kalıyor,
yeni siparişler doğru hesaplanıyor.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '61cb2ddf74fa'
down_revision: Union[str, None] = 'a2e20db52f70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('orders') as batch_op:
        batch_op.alter_column('unit_price', new_column_name='net', existing_type=sa.Numeric(precision=12, scale=2))
        batch_op.add_column(
            sa.Column('vat_amount', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0.00')
        )


def downgrade() -> None:
    with op.batch_alter_table('orders') as batch_op:
        batch_op.drop_column('vat_amount')
        batch_op.alter_column('net', new_column_name='unit_price', existing_type=sa.Numeric(precision=12, scale=2))
