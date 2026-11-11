from django.db import migrations, models


class Migration(migrations.Migration):
    """Lot 13 : préférences du chat (fournisseur, modèle par fournisseur) gardées en base.
    Ajout de colonnes seulement."""

    dependencies = [
        ('api', '0013_albert_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='aikeyvault',
            name='preferred_provider',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='aikeyvault',
            name='preferred_models',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
