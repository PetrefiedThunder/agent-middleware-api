"""Harden the human-approval gate: bind approvals to the request, repair
the SQLite boolean backfill from 023.

Two changes:

1. ``human_approvals.request_hash`` — sha256 of the ``(tool, arguments)`` the
   human reviewed. Lets a reloaded approval reject an invoke that reused the
   same idempotency key with different arguments.

2. Repair ``permits.requires_human_approval`` on SQLite. Migration 023 added
   the column with ``server_default="false"`` — a plain string that SQLite
   stores as the *text* ``'false'`` and then reads back through SQLAlchemy's
   non-native Boolean as ``True`` (``bool("false")``). Every permit that
   existed before 023 therefore reports ``requires_human_approval=True`` and
   fails signature verification (the flag enters the signed payload only when
   true). Postgres parses ``'false'`` as boolean false, so it is unaffected;
   the repair runs on SQLite only, normalizing any non-0/1 value back to 0.

Revision ID: 024_human_approval_hardening
Revises: 023_human_approval_gate
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "024_human_approval_hardening"
down_revision: Union[str, None] = "023_human_approval_gate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "human_approvals",
        sa.Column("request_hash", sa.String(length=64), nullable=True),
    )

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # Existing rows backfilled by 023 hold the text 'false'; coerce any
        # value that is not already the integer 0/1 back to 0 (false).
        op.execute(
            sa.text(
                "UPDATE permits SET requires_human_approval = 0 "
                "WHERE requires_human_approval NOT IN (0, 1)"
            )
        )


def downgrade() -> None:
    op.drop_column("human_approvals", "request_hash")
