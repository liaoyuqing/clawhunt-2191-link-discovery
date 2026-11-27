"""Create intel link discovery tables

Revision ID: 0001_intel_discovery
Revises:
Create Date: 2026-03-12

The migration creates only the two tables discovery owns.  ``intel_raw_pages``
is created by the raw-page crawler ticket’s migration and is referenced here
only for its unique ``(org_id, url_hash)`` index, which is what makes the
incremental check a single indexed lookup.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_intel_discovery"
down_revision = None
branch_labels = None
depends_on = None


def _audit_columns() -> list:
    """The six platform-wide audit columns required on every business table."""
    return [
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default="system"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "intel_discovery_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        *_audit_columns(),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("entry_url", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="html_list"),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_robots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_host", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_invalid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_intel_discovery_batches_org_id", "intel_discovery_batches", ["org_id"])
    op.create_index("ix_intel_discovery_batches_site_id", "intel_discovery_batches", ["site_id"])
    op.create_index("ix_intel_discovery_batches_source_id", "intel_discovery_batches", ["source_id"])

    op.create_table(
        "intel_discovered_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        *_audit_columns(),
        sa.Column(
            "batch_id",
            sa.String(length=36),
            sa.ForeignKey("intel_discovery_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("anchor_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("pub_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("found_on", sa.Text(), nullable=False, server_default=""),
        sa.Column("page_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_attachment", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("batch_id", "url_hash", name="uq_intel_discovered_links_batch_url_hash"),
    )
    op.create_index("ix_intel_discovered_links_org_id", "intel_discovered_links", ["org_id"])
    op.create_index("ix_intel_discovered_links_site_id", "intel_discovered_links", ["site_id"])
    op.create_index(
        "ix_intel_discovered_links_org_url_hash",
        "intel_discovered_links",
        ["org_id", "url_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_intel_discovered_links_org_url_hash", table_name="intel_discovered_links")
    op.drop_index("ix_intel_discovered_links_site_id", table_name="intel_discovered_links")
    op.drop_index("ix_intel_discovered_links_org_id", table_name="intel_discovered_links")
    op.drop_table("intel_discovered_links")
    op.drop_index("ix_intel_discovery_batches_source_id", table_name="intel_discovery_batches")
    op.drop_index("ix_intel_discovery_batches_site_id", table_name="intel_discovery_batches")
    op.drop_index("ix_intel_discovery_batches_org_id", table_name="intel_discovery_batches")
    op.drop_table("intel_discovery_batches")
