"""eklenti eş-sonlanma: temel aboneliğe bağlama, orantılı sipariş, yenileme satırları

Kullanıcı kararı (2026-10-12): eklenti (ör. colege_soru) bağlı olduğu temel
aboneliğin (colEGE) bitişiyle AYNI gün biter.
- subscriptions.base_subscription_id: eklenti aboneliğinin bağlı olduğu temel abonelik
- orders.base_subscription_id / addon_period_end / prorated_days: eklenti
  siparişinin bağlandığı abonelik, hedef bitiş ve orantılanan gün sayısı
- order_addons: temel abonelik yenileme siparişine eklenen eklenti satırları
Mevcut satırlar NULL kalır. Bkz. app/services/eklentiler.py.

Revision ID: c4f81a2d7e55
Revises: 9b6e3d1c4a20
Create Date: 2026-10-12 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f81a2d7e55'
down_revision: Union[str, None] = '9b6e3d1c4a20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('base_subscription_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_subscriptions_base_subscription_id_subscriptions', 'subscriptions', ['base_subscription_id'], ['id']
        )
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('base_subscription_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('addon_period_end', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('prorated_days', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_orders_base_subscription_id_subscriptions', 'subscriptions', ['base_subscription_id'], ['id']
        )
    op.create_table(
        'order_addons',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('net', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id']),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('order_addons')
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_constraint('fk_orders_base_subscription_id_subscriptions', type_='foreignkey')
        batch_op.drop_column('prorated_days')
        batch_op.drop_column('addon_period_end')
        batch_op.drop_column('base_subscription_id')
    with op.batch_alter_table('subscriptions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_subscriptions_base_subscription_id_subscriptions', type_='foreignkey')
        batch_op.drop_column('base_subscription_id')
