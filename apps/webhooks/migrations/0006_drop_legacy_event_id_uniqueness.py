from django.db import migrations


def drop_legacy_event_id_uniqueness(apps, schema_editor) -> None:
    """Repair production schemas that still make HubSpot event IDs unique."""
    connection = schema_editor.connection
    table_name = "webhook_events"
    quote = connection.ops.quote_name

    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table_name)

    for name, details in constraints.items():
        columns = list(details.get("columns") or [])
        if not details.get("unique") or columns != ["event_id"]:
            continue

        if details.get("index"):
            schema_editor.execute(f"DROP INDEX IF EXISTS {quote(name)}")
        elif connection.vendor == "postgresql":
            schema_editor.execute(f"ALTER TABLE {quote(table_name)} DROP CONSTRAINT IF EXISTS {quote(name)}")
        elif connection.vendor == "mysql":
            schema_editor.execute(f"ALTER TABLE {quote(table_name)} DROP INDEX {quote(name)}")
        else:
            raise RuntimeError(f"Cannot safely remove legacy unique constraint {name!r} from {connection.vendor!r}.")


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0005_webhookevent_deduplication_key"),
    ]

    operations = [
        migrations.RunPython(
            drop_legacy_event_id_uniqueness,
            migrations.RunPython.noop,
        ),
    ]
