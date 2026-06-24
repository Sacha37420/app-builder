from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0002_enrich'),
    ]

    operations = [
        migrations.AddField(
            model_name='appspec',
            name='chat_history',
            field=models.JSONField(default=list),
        ),
    ]
