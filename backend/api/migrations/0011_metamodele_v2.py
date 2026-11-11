from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0010_ai_key_vault'),
    ]

    # Métamodèle v2 (chantier app-builder-v2, I1). Colonnes ajoutées seulement,
    # toutes avec une valeur par défaut : aucune donnée existante n'est modifiée,
    # les colonnes que lab-admin lit ne changent ni de nom ni de type. Écrite à la
    # main (voir 0008 : `makemigrations` voudrait aussi changer les clés primaires).
    operations = [
        migrations.AddField(model_name='appspec', name='roles', field=models.JSONField(default=list)),
        migrations.AddField(model_name='appspec', name='jobs', field=models.JSONField(default=list)),
        migrations.AddField(model_name='appspec', name='integrations', field=models.JSONField(default=list)),
        migrations.AddField(model_name='appspec', name='external_apis', field=models.JSONField(default=list)),
        migrations.AddField(model_name='appspec', name='extensions', field=models.JSONField(default=dict)),
        migrations.AddField(model_name='datamodel', name='kind',
                            field=models.CharField(default='entity', max_length=20)),
        migrations.AddField(model_name='datamodel', name='access', field=models.JSONField(default=dict)),
        migrations.AddField(model_name='datamodel', name='states', field=models.JSONField(default=dict)),
        migrations.AddField(model_name='datamodel', name='constraints', field=models.JSONField(default=list)),
        migrations.AddField(model_name='endpoint', name='auth', field=models.JSONField(default=dict)),
        migrations.AddField(model_name='page', name='public', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='page', name='public_reason',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='page', name='required_roles', field=models.JSONField(default=list)),
    ]
