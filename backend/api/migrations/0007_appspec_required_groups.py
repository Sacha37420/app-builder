from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0006_pipeline_trigger_interaction'),
    ]

    operations = [
        migrations.AddField(
            model_name='appspec',
            name='required_groups',
            field=models.JSONField(default=list),
        ),
    ]
