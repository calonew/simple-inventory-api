"""create machines, products and inventory tables

Revision ID: 0001
Revises: 
Create Date: 2026-10-10 17:11:11.503388

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('machines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('location', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('products',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('price', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('inventory',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('machine_id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['machine_id'], ['machines.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('machine_id', 'product_id')
    )


def downgrade() -> None:
    op.drop_table('inventory')
    op.drop_table('products')
    op.drop_table('machines')
