"""havale eft elle odeme isaretleme

Revision ID: 782028e062d9
Revises: 171595714890
Create Date: 2026-10-05 13:41:09.478623

KARAR (2026-10-05, kullanıcı): bvpay banka bilgilerini beklerken havale/EFT
siparişleri personel ELLE "ödendi" işaretleyebilsin. `payments.bvpay_payment_id`
artık NULLABLE — havale/EFT ödemelerinde bvpay hiç devreye girmiyor
(`bank_reference` o ödemenin tekil anahtarı, bkz. app/models.py::Payment).

Autogenerate bu değişiklikleri (nullable gevşetme, UNIQUE/FK ekleme) düz
`op.alter_column`/`op.create_unique_constraint`/`op.create_foreign_key`
olarak üretti — SQLite bunların HİÇBİRİNİ düz ALTER TABLE ile desteklemiyor
("near ALTER: syntax error", elle denendi). Hepsi `op.batch_alter_table`
içine alındı (projedeki önceki rename migration'ındaki AYNI SQLite-güvenli
desen). `payment_method` var olan satırlar için `server_default='bvpay'`
alıyor (NOT NULL + mevcut veri güvenliği, bkz. `is_staff` migration'ındaki
aynı gerekçe).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '782028e062d9'
down_revision: Union[str, None] = '171595714890'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('payments') as batch_op:
        batch_op.alter_column('bvpay_payment_id', existing_type=sa.VARCHAR(length=100), nullable=True)
        batch_op.add_column(
            sa.Column(
                'payment_method',
                sa.Enum('BVPAY', 'BANK_TRANSFER', name='paymentmethod', native_enum=False, length=20),
                nullable=False,
                server_default='bvpay',
            )
        )
        batch_op.add_column(sa.Column('bank_reference', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('marked_by_user_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('received_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint('uq_payments_bank_reference', ['bank_reference'])
        batch_op.create_foreign_key('fk_payments_marked_by_user_id_users', 'users', ['marked_by_user_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('payments') as batch_op:
        batch_op.drop_constraint('fk_payments_marked_by_user_id_users', type_='foreignkey')
        batch_op.drop_constraint('uq_payments_bank_reference', type_='unique')
        batch_op.drop_column('received_at')
        batch_op.drop_column('note')
        batch_op.drop_column('marked_by_user_id')
        batch_op.drop_column('bank_reference')
        batch_op.drop_column('payment_method')
        batch_op.alter_column('bvpay_payment_id', existing_type=sa.VARCHAR(length=100), nullable=False)
