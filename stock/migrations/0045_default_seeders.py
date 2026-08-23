from django.db import migrations


def run_seeders(apps, schema_editor):
    from stock.default_seeders import seed_defaults

    seed_defaults(using=schema_editor.connection.alias)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0044_souscategorie'),
        ('Userauths', '0019_pwd_forget_purpose'),
    ]

    operations = [
        migrations.RunPython(run_seeders, noop),
    ]
