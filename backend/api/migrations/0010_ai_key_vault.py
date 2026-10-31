import api.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0009_cadriciel'),
    ]

    # Une table neuve seulement (voir 0008 : `makemigrations` voudrait aussi
    # changer les clés primaires existantes, que lab-admin lit).
    operations = [
        migrations.CreateModel(
            name='AiKeyVault',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('owner_email', models.EmailField(max_length=255, unique=True)),
                ('claude_key', api.fields.EncryptedTextField(blank=True, default='')),
                ('mistral_key', api.fields.EncryptedTextField(blank=True, default='')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'ai_key_vault',
            },
        ),
    ]
