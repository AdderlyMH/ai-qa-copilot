"""Create immutable evaluation human-review and adjudication state.

Revision ID: 0016_evaluation_reviews
Revises: 0015_quality_report_revisions
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0016_evaluation_reviews"
down_revision: str | None = "0015_quality_report_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable EVAL-003 reviewer and adjudication evidence."""

    op.create_table(
        "evaluation_reviewer_attestations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.String(length=255), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("rubric_version", sa.String(length=64), nullable=False),
        sa.Column("qualification_summary", sa.Text(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("independent", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(reviewer_id)) > 0",
            name="ck_evaluation_reviewer_attestations_reviewer_id_present",
        ),
        sa.CheckConstraint(
            "length(trim(dataset_version)) > 0",
            name="ck_evaluation_reviewer_attestations_dataset_version_present",
        ),
        sa.CheckConstraint(
            "length(trim(rubric_version)) > 0",
            name="ck_evaluation_reviewer_attestations_rubric_version_present",
        ),
        sa.CheckConstraint(
            "length(trim(qualification_summary)) > 0",
            name="ck_evaluation_reviewer_attestations_qualification_present",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_evaluation_reviewer_attestations",
        ),
    )

    op.create_table(
        "evaluation_review_labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("case_sha256", sa.String(length=64), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("rubric_version", sa.String(length=64), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("reviewer_id", sa.String(length=255), nullable=False),
        sa.Column("reviewer_attestation_id", sa.Uuid(), nullable=False),
        sa.Column("label_json", sa.Text(), nullable=False),
        sa.Column("label_sha256", sa.String(length=64), nullable=False),
        sa.Column("candidate_output_sha256", sa.String(length=64), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", sa.Uuid(), nullable=True),
        sa.Column("primary_label_id", sa.Uuid(), nullable=True),
        sa.Column("independent_label_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(case_id)) > 0",
            name="ck_evaluation_review_labels_case_id_present",
        ),
        sa.CheckConstraint(
            "length(case_sha256) = 64",
            name="ck_evaluation_review_labels_case_sha256_length",
        ),
        sa.CheckConstraint(
            "length(trim(dataset_version)) > 0",
            name="ck_evaluation_review_labels_dataset_version_present",
        ),
        sa.CheckConstraint(
            "length(trim(rubric_version)) > 0",
            name="ck_evaluation_review_labels_rubric_version_present",
        ),
        sa.CheckConstraint(
            "subject_kind IN ('finding', 'test_case', 'failure_analysis')",
            name="ck_evaluation_review_labels_subject_kind_allowed",
        ),
        sa.CheckConstraint(
            "length(trim(subject_id)) > 0",
            name="ck_evaluation_review_labels_subject_id_present",
        ),
        sa.CheckConstraint(
            "role IN ('primary', 'independent', 'adjudicated')",
            name="ck_evaluation_review_labels_role_allowed",
        ),
        sa.CheckConstraint(
            "length(trim(reviewer_id)) > 0",
            name="ck_evaluation_review_labels_reviewer_id_present",
        ),
        sa.CheckConstraint(
            "length(trim(label_json)) > 0",
            name="ck_evaluation_review_labels_label_json_present",
        ),
        sa.CheckConstraint(
            "length(label_sha256) = 64",
            name="ck_evaluation_review_labels_label_sha256_length",
        ),
        sa.CheckConstraint(
            "candidate_output_sha256 IS NULL OR length(candidate_output_sha256) = 64",
            name="ck_evaluation_review_labels_candidate_sha256_length",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_evaluation_review_labels_revision_positive",
        ),
        sa.CheckConstraint(
            "(role = 'primary' "
            "AND primary_label_id IS NULL "
            "AND independent_label_id IS NULL) OR "
            "(role = 'independent' "
            "AND primary_label_id IS NOT NULL "
            "AND independent_label_id IS NULL "
            "AND candidate_output_sha256 IS NULL) OR "
            "(role = 'adjudicated' "
            "AND primary_label_id IS NOT NULL "
            "AND independent_label_id IS NOT NULL "
            "AND candidate_output_sha256 IS NULL)",
            name="ck_evaluation_review_labels_role_linkage",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_attestation_id"],
            ["evaluation_reviewer_attestations.id"],
            name="fk_evaluation_review_labels_attestation",
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"],
            ["evaluation_review_labels.id"],
            name="fk_evaluation_review_labels_parent",
        ),
        sa.ForeignKeyConstraint(
            ["primary_label_id"],
            ["evaluation_review_labels.id"],
            name="fk_evaluation_review_labels_primary",
        ),
        sa.ForeignKeyConstraint(
            ["independent_label_id"],
            ["evaluation_review_labels.id"],
            name="fk_evaluation_review_labels_independent",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_review_labels"),
        sa.UniqueConstraint(
            "case_id",
            "subject_kind",
            "subject_id",
            "role",
            "revision_number",
            name="uq_evaluation_review_labels_revision",
        ),
    )

    op.create_table(
        "evaluation_review_disagreements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("primary_label_id", sa.Uuid(), nullable=False),
        sa.Column("independent_label_id", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.Text(), nullable=False),
        sa.Column("primary_value_json", sa.Text(), nullable=False),
        sa.Column("independent_value_json", sa.Text(), nullable=False),
        sa.Column("material", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(field_path)) > 0",
            name="ck_evaluation_review_disagreements_field_path_present",
        ),
        sa.CheckConstraint(
            "length(trim(primary_value_json)) > 0",
            name="ck_evaluation_review_disagreements_primary_value_present",
        ),
        sa.CheckConstraint(
            "length(trim(independent_value_json)) > 0",
            name="ck_evaluation_review_disagreements_independent_value_present",
        ),
        sa.ForeignKeyConstraint(
            ["primary_label_id"],
            ["evaluation_review_labels.id"],
            name="fk_evaluation_review_disagreements_primary",
        ),
        sa.ForeignKeyConstraint(
            ["independent_label_id"],
            ["evaluation_review_labels.id"],
            name="fk_evaluation_review_disagreements_independent",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_review_disagreements"),
        sa.UniqueConstraint(
            "primary_label_id",
            "independent_label_id",
            "field_path",
            name="uq_evaluation_review_disagreements_field",
        ),
    )

    op.create_table(
        "evaluation_review_adjudications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("disagreement_id", sa.Uuid(), nullable=False),
        sa.Column("adjudicated_label_id", sa.Uuid(), nullable=False),
        sa.Column("adjudicator_id", sa.String(length=255), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(adjudicator_id)) > 0",
            name="ck_evaluation_review_adjudications_adjudicator_present",
        ),
        sa.CheckConstraint(
            "length(trim(rationale)) > 0",
            name="ck_evaluation_review_adjudications_rationale_present",
        ),
        sa.ForeignKeyConstraint(
            ["disagreement_id"],
            ["evaluation_review_disagreements.id"],
            name="fk_evaluation_review_adjudications_disagreement",
        ),
        sa.ForeignKeyConstraint(
            ["adjudicated_label_id"],
            ["evaluation_review_labels.id"],
            name="fk_evaluation_review_adjudications_label",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_review_adjudications"),
        sa.UniqueConstraint(
            "disagreement_id",
            name="uq_evaluation_review_adjudications_disagreement",
        ),
    )

    op.create_index(
        "ix_evaluation_reviewer_attestations_reviewer_created_at",
        "evaluation_reviewer_attestations",
        ["reviewer_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_review_labels_case_subject_created_at",
        "evaluation_review_labels",
        ["case_id", "subject_kind", "subject_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_review_disagreements_labels_created_at",
        "evaluation_review_disagreements",
        ["primary_label_id", "independent_label_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only EVAL-003 durable review state."""

    op.drop_index(
        "ix_evaluation_review_disagreements_labels_created_at",
        table_name="evaluation_review_disagreements",
    )
    op.drop_index(
        "ix_evaluation_review_labels_case_subject_created_at",
        table_name="evaluation_review_labels",
    )
    op.drop_index(
        "ix_evaluation_reviewer_attestations_reviewer_created_at",
        table_name="evaluation_reviewer_attestations",
    )
    op.drop_table("evaluation_review_adjudications")
    op.drop_table("evaluation_review_disagreements")
    op.drop_table("evaluation_review_labels")
    op.drop_table("evaluation_reviewer_attestations")
