"""Seed microtrading portfolios — micro-500 + micro-100k (M3)

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-13
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirror the daily two-budget pattern (Cartera 500 / 100K) for microtrading. Both run
# the m1 control version; the m1-vs-m2 A/B is done by relabelling one (or adding more)
# via PATCH /api/portfolios/{id} at runtime — budgets stay editable via cash_movements.
_PORTFOLIOS = (
    ("micro-500", 500, "m1"),
    ("micro-100k", 100000, "m1"),
)


def upgrade() -> None:
    # Idempotent-ish: skip a name that already exists (a re-run / manual create) so the
    # unique(name) constraint can't abort the migration. kind='micro' keeps them out of
    # the daily pipeline (which filters kind='daily'); they sit in cash until the
    # intraday jobs trade them.
    for name, budget, label in _PORTFOLIOS:
        op.execute(
            "INSERT INTO portfolios (name, active, kind, strategy_label, created_at) "
            f"SELECT '{name}', true, 'micro', '{label}', now() "
            f"WHERE NOT EXISTS (SELECT 1 FROM portfolios WHERE name = '{name}')"
        )
        op.execute(
            "INSERT INTO cash_movements (portfolio_id, kind, amount, ts, note) "
            f"SELECT id, 'deposit', {budget}, now(), 'Initial budget' "
            f"FROM portfolios WHERE name = '{name}' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM cash_movements cm WHERE cm.portfolio_id = portfolios.id"
            ")"
        )


def downgrade() -> None:
    # FK cascade clears their cash_movements/positions/trades/NAV.
    names = ", ".join(f"'{name}'" for name, _, _ in _PORTFOLIOS)
    op.execute(f"DELETE FROM portfolios WHERE name IN ({names})")
