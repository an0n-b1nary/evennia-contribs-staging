from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("evennia_jobs", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="job",
            options={"ordering": ["created_at"]},
        ),
    ]
