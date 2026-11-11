import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0011_metamodele_v2'),
    ]

    # Une table neuve seulement (I5 du chantier app-builder-v2).
    operations = [
        migrations.CreateModel(
            name='McpToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('owner_email', models.EmailField(db_index=True, max_length=255)),
                ('name', models.CharField(max_length=80)),
                ('prefix', models.CharField(max_length=12)),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('scope', models.CharField(default='lire', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('spec', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                                           related_name='mcp_tokens', to='api.appspec')),
            ],
            options={'db_table': 'mcp_tokens'},
        ),
    ]
