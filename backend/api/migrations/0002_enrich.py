from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0001_initial'),
    ]

    operations = [
        # ── DataModel ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='DataModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('fields', models.JSONField(default=list)),
                ('relationships', models.JSONField(default=list)),
                ('order', models.PositiveIntegerField(default=0)),
                ('app', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                          related_name='data_models', to='api.appspec')),
            ],
            options={'db_table': 'data_models', 'ordering': ['order', 'name']},
        ),

        # ── Endpoint : nouveaux champs sémantiques ───────────────────────────
        migrations.AddField(
            model_name='endpoint',
            name='operation',
            field=models.CharField(
                choices=[('list','List'),('create','Create'),('retrieve','Retrieve'),
                         ('update','Update'),('partial_update','Partial Update'),
                         ('delete','Delete'),('custom','Custom')],
                default='custom', max_length=20),
        ),
        migrations.AddField(
            model_name='endpoint',
            name='linked_model_name',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='endpoint',
            name='auth_required',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='endpoint',
            name='required_roles',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='endpoint',
            name='request_schema',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='endpoint',
            name='response_schema',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='endpoint',
            name='query_params',
            field=models.JSONField(default=list),
        ),

        # ── Page : layout + components ───────────────────────────────────────
        migrations.AddField(
            model_name='page',
            name='layout',
            field=models.CharField(
                choices=[('list','Liste / tableau'),('detail','Vue détail'),
                         ('form','Formulaire'),('dashboard','Dashboard'),('mixed','Mixte')],
                default='mixed', max_length=20),
        ),
        migrations.AddField(
            model_name='page',
            name='components',
            field=models.JSONField(default=list),
        ),
    ]
