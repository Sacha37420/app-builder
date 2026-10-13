from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0008_patch_applications'),
    ]

    # Colonnes ajoutées seulement (toutes avec une valeur par défaut) : aucune
    # donnée existante n'est modifiée, et les colonnes que lab-admin lit ne
    # changent ni de nom ni de type. Écrite à la main pour la même raison que
    # 0008 (`makemigrations` voudrait aussi changer les clés primaires).
    operations = [
        migrations.AddField(
            model_name='appspec',
            name='project_name',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.AddField(
            model_name='appspec',
            name='business_rules',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='appspec',
            name='uses_email',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='endpoint',
            name='public_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='appspec',
            name='app_type',
            field=models.CharField(
                choices=[('django-angular', 'Django + Angular'), ('django', 'Django seul'),
                         ('angular', 'Angular seul'), ('spring-angular', 'Spring + Angular'),
                         ('spring', 'Spring seul')],
                default='django-angular', max_length=30),
        ),
    ]
