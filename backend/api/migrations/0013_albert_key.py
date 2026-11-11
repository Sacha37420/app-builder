import api.fields
from django.db import migrations


class Migration(migrations.Migration):
    """Lot 12 : clé d'API Albert (DINUM) au coffre, chiffrée comme les autres.
    Ajout d'une colonne seulement (voir 0008 : pas de `makemigrations` aveugle,
    il voudrait changer des clés primaires que lab-admin lit)."""

    dependencies = [
        ('api', '0012_mcp_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='aikeyvault',
            name='albert_key',
            field=api.fields.EncryptedTextField(blank=True, default=''),
        ),
    ]
