from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0005_appspec_app_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='pipeline',
            name='trigger_interaction',
            field=models.CharField(blank=True, default='', max_length=200),
            preserve_default=False,
        ),
    ]
