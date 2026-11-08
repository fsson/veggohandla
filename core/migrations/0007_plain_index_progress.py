import json

from django.db import migrations


def to_text(apps, schema_editor):
    """Progress used to be stored as JSON (message id + params); it is plain Swedish text now."""
    AppSettings = apps.get_model("core", "AppSettings")
    for s in AppSettings.objects.all():
        try:
            data = json.loads(s.index_progress)
            s.index_progress = (data["m"] % data["p"])[:400]
        except (ValueError, KeyError, TypeError):
            continue
        s.save(update_fields=["index_progress"])


class Migration(migrations.Migration):
    dependencies = [("core", "0006_recipe_image_credit")]
    operations = [migrations.RunPython(to_text, migrations.RunPython.noop)]
