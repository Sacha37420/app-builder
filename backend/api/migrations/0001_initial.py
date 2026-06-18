from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name='AppSpec',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('owner_email', models.EmailField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'app_specs', 'ordering': ['-updated_at']},
        ),
        migrations.CreateModel(
            name='EndpointGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('app', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                          related_name='endpoint_groups', to='api.appspec')),
            ],
            options={'db_table': 'endpoint_groups', 'ordering': ['order', 'name']},
        ),
        migrations.CreateModel(
            name='Endpoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('method', models.CharField(
                    choices=[('GET','GET'),('POST','POST'),('PUT','PUT'),
                             ('PATCH','PATCH'),('DELETE','DELETE')],
                    max_length=10)),
                ('path', models.CharField(max_length=500)),
                ('description', models.TextField(blank=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                            related_name='endpoints', to='api.endpointgroup')),
            ],
            options={'db_table': 'endpoints', 'ordering': ['order', 'path']},
        ),
        migrations.CreateModel(
            name='FrontendService',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('order', models.PositiveIntegerField(default=0)),
                ('app', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                          related_name='services', to='api.appspec')),
                ('endpoint_groups', models.ManyToManyField(blank=True, related_name='services',
                                                            to='api.endpointgroup')),
            ],
            options={'db_table': 'frontend_services', 'ordering': ['order', 'name']},
        ),
        migrations.CreateModel(
            name='Page',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('route', models.CharField(max_length=500)),
                ('order', models.PositiveIntegerField(default=0)),
                ('app', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                          related_name='pages', to='api.appspec')),
                ('services', models.ManyToManyField(blank=True, related_name='pages',
                                                    to='api.frontendservice')),
            ],
            options={'db_table': 'pages', 'ordering': ['order', 'name']},
        ),
        migrations.CreateModel(
            name='Interaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('type', models.CharField(
                    choices=[('click','Clic'),('form','Formulaire'),
                             ('navigation','Navigation'),('display','Affichage'),('other','Autre')],
                    max_length=50)),
                ('description', models.TextField(blank=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('page', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='interactions', to='api.page')),
            ],
            options={'db_table': 'interactions', 'ordering': ['order']},
        ),
        migrations.CreateModel(
            name='Pipeline',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('steps', models.JSONField(default=list)),
                ('order', models.PositiveIntegerField(default=0)),
                ('page', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='pipelines', to='api.page')),
            ],
            options={'db_table': 'pipelines', 'ordering': ['order', 'name']},
        ),
    ]
