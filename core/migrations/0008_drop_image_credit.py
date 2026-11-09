from django.db import migrations


def clear_seed_photos(apps, schema_editor):
    """The bundled recipes no longer have photos: drop the ones seeded earlier (they had a credit)."""
    Recipe = apps.get_model("core", "Recipe")
    Recipe.objects.exclude(image_credit="").update(image="")


class Migration(migrations.Migration):
    dependencies = [("core", "0007_plain_index_progress")]

    operations = [
        migrations.RunPython(clear_seed_photos, migrations.RunPython.noop),
        migrations.RemoveField(model_name="recipe", name="image_credit"),
        migrations.RemoveField(model_name="recipe", name="image_source"),
    ]
