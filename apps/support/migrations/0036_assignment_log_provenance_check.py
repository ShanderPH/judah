"""Converge legacy and canonical assignment provenance without rewriting rows.

PostgreSQL validation precedes replacement of the existing check. The forward
operation can resume after interruption; a constraint comment records whether
rollback must restore the legacy check or its original absence.
"""

from __future__ import annotations

from django.db import migrations, models, transaction
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

CONSTRAINT_NAME = "assignment_logs_assignment_type_check"
NEXT_CONSTRAINT_NAME = "assignment_logs_assignment_type_next_check"
LEGACY_CONSTRAINT_NAME = "assignment_logs_assignment_type_legacy_check"
CANONICAL_TYPES = (
    "automatic_assignment",
    "manual_assignment",
    "owner_change",
    "forced_reassignment",
    "external_integration",
    "unknown_external",
)
LEGACY_TYPES = ("auto", "automatic", "manual")


def _constraint_definition(schema_editor: BaseDatabaseSchemaEditor, name: str) -> str | None:
    """Read the named assignment log check from the PostgreSQL catalog."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'assignment_logs'::regclass AND conname = %s",
            [name],
        )
        row = cursor.fetchone()
    return str(row[0]) if row else None


def _constraint_comment(schema_editor: BaseDatabaseSchemaEditor, name: str) -> str | None:
    """Read the prior-schema marker retained on the assignment log check."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT obj_description(oid, 'pg_constraint') FROM pg_constraint "
            "WHERE conrelid = 'assignment_logs'::regclass AND conname = %s",
            [name],
        )
        row = cursor.fetchone()
    return str(row[0]) if row and row[0] is not None else None


def replace_check(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Validate the wider check before removing the live legacy check.

    Args:
        apps: Historical model registry for non-PostgreSQL schema updates.
        schema_editor: Migration connection used for validation and replacement.
    """
    if schema_editor.connection.vendor != "postgresql":
        model = apps.get_model("support", "AssignmentLog")
        constraint = models.CheckConstraint(
            condition=models.Q(assignment_type__in=(*LEGACY_TYPES, *CANONICAL_TYPES)),
            name=CONSTRAINT_NAME,
        )
        model._meta.constraints = [item for item in model._meta.constraints if item.name != CONSTRAINT_NAME]
        model._meta.constraints = [*model._meta.constraints, constraint]
        schema_editor.add_constraint(model, constraint)
        return

    current = _constraint_definition(schema_editor, CONSTRAINT_NAME)
    if current and all(f"'{value}'" in current for value in (*LEGACY_TYPES, *CANONICAL_TYPES)):
        return
    if _constraint_definition(schema_editor, NEXT_CONSTRAINT_NAME) is None:
        allowed = ", ".join(f"'{value}'" for value in (*LEGACY_TYPES, *CANONICAL_TYPES))
        schema_editor.execute(
            f"ALTER TABLE assignment_logs ADD CONSTRAINT {NEXT_CONSTRAINT_NAME} "
            f"CHECK (assignment_type IN ({allowed})) NOT VALID"
        )
    if _constraint_comment(schema_editor, NEXT_CONSTRAINT_NAME) is None:
        prior = "legacy" if current else "absent"
        schema_editor.execute(
            f"COMMENT ON CONSTRAINT {NEXT_CONSTRAINT_NAME} ON assignment_logs IS 'judah:assignment_type_prior={prior}'"
        )
    schema_editor.execute(f"ALTER TABLE assignment_logs VALIDATE CONSTRAINT {NEXT_CONSTRAINT_NAME}")
    schema_editor.execute(f"ALTER TABLE assignment_logs DROP CONSTRAINT IF EXISTS {CONSTRAINT_NAME}")
    schema_editor.execute(f"ALTER TABLE assignment_logs RENAME CONSTRAINT {NEXT_CONSTRAINT_NAME} TO {CONSTRAINT_NAME}")


def restore_legacy_check(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Restore the prior check without changing historical provenance.

    Legacy validation and replacement share a transaction, so incompatible rows
    reject rollback while leaving the wider check intact.

    Args:
        apps: Historical model registry for non-PostgreSQL schema updates.
        schema_editor: Migration connection used to restore the prior schema.

    Raises:
        RuntimeError: The prior-schema marker is missing or unrecognized.
        IntegrityError: Existing canonical-only values prevent legacy validation.
    """
    if schema_editor.connection.vendor != "postgresql":
        model = apps.get_model("support", "AssignmentLog")
        constraint = models.CheckConstraint(
            condition=models.Q(assignment_type__in=(*LEGACY_TYPES, *CANONICAL_TYPES)),
            name=CONSTRAINT_NAME,
        )
        model._meta.constraints = [item for item in model._meta.constraints if item.name != CONSTRAINT_NAME]
        schema_editor.remove_constraint(model, constraint)
        return

    current = _constraint_definition(schema_editor, CONSTRAINT_NAME)
    if current and "unknown_external" not in current:
        return
    prior = _constraint_comment(schema_editor, CONSTRAINT_NAME)
    if prior == "judah:assignment_type_prior=absent":
        schema_editor.execute(f"ALTER TABLE assignment_logs DROP CONSTRAINT {CONSTRAINT_NAME}")
        return
    if prior != "judah:assignment_type_prior=legacy":
        raise RuntimeError("Cannot reverse assignment log check without its prior-schema marker")
    allowed = ", ".join(f"'{value}'" for value in LEGACY_TYPES)
    with transaction.atomic(using=schema_editor.connection.alias):
        schema_editor.execute(
            f"ALTER TABLE assignment_logs ADD CONSTRAINT {LEGACY_CONSTRAINT_NAME} "
            f"CHECK (assignment_type IN ({allowed})) NOT VALID"
        )
        schema_editor.execute(f"ALTER TABLE assignment_logs VALIDATE CONSTRAINT {LEGACY_CONSTRAINT_NAME}")
        schema_editor.execute(f"ALTER TABLE assignment_logs DROP CONSTRAINT {CONSTRAINT_NAME}")
        schema_editor.execute(
            f"ALTER TABLE assignment_logs RENAME CONSTRAINT {LEGACY_CONSTRAINT_NAME} TO {CONSTRAINT_NAME}"
        )


class Migration(migrations.Migration):
    """Align Django state with the resumable PostgreSQL check replacement."""

    atomic = False

    dependencies = [("support", "0035_alter_assignedconversation_assigned_at")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(replace_check, restore_legacy_check, atomic=False)],
            state_operations=[
                migrations.AddConstraint(
                    model_name="assignmentlog",
                    constraint=models.CheckConstraint(
                        condition=models.Q(assignment_type__in=(*LEGACY_TYPES, *CANONICAL_TYPES)),
                        name=CONSTRAINT_NAME,
                    ),
                ),
            ],
        ),
    ]
