from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0004_endpoint_steps'),
    ]

    operations = [
        migrations.AddField(
            model_name='appspec',
            name='app_type',
            field=models.CharField(
                choices=[
                    ('django-angular', 'Django + Angular'),
                    ('django',         'Django seul'),
                    ('spring-angular', 'Spring + Angular'),
                    ('spring',         'Spring seul'),
                    ('angular',        'Angular seul'),
                ],
                default='django-angular',
                max_length=30,
            ),
        ),
    ]
