from django.db import migrations, models


class Migration(migrations.Migration):
    """Phase 3: scans are linked to the visitor by the session key."""

    dependencies = [
        ("scans", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="scan",
            old_name="owner_id",
            new_name="session_key",
        ),
        migrations.AlterField(
            model_name="scan",
            name="session_key",
            field=models.CharField(db_index=True, max_length=40),
        ),
    ]
