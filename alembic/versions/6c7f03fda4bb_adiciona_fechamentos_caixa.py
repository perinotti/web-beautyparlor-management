"""adiciona fechamentos de caixa

Revision ID: 6c7f03fda4bb
Revises: ff8b2ae2b855
Create Date: 2026-05-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6c7f03fda4bb"
down_revision = "ff8b2ae2b855"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fechamentos_caixa",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("data_fechamento", sa.Date(), nullable=False),
        sa.Column("saldo_final", sa.Numeric(10, 2), nullable=False),
        sa.Column("data_hora_fechamento", sa.DateTime(), nullable=False),
        sa.Column("funcionario_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["funcionario_id"], ["funcionarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fechamentos_caixa_data_fechamento"), "fechamentos_caixa", ["data_fechamento"], unique=True)
    op.create_index(op.f("ix_fechamentos_caixa_id"), "fechamentos_caixa", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_fechamentos_caixa_id"), table_name="fechamentos_caixa")
    op.drop_index(op.f("ix_fechamentos_caixa_data_fechamento"), table_name="fechamentos_caixa")
    op.drop_table("fechamentos_caixa")
