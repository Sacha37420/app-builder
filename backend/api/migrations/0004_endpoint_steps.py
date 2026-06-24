from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0003_appspec_chat_history')]
    operations = [
        migrations.AddField(
            model_name='endpoint',
            name='steps',
            field=models.JSONField(default=list),
        ),
    ]
