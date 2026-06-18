from django.db import models


class AppSpec(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owner_email = models.EmailField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'app_specs'
        ordering = ['-updated_at']

    def __str__(self):
        return self.name


class EndpointGroup(models.Model):
    app = models.ForeignKey(AppSpec, related_name='endpoint_groups', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'endpoint_groups'
        ordering = ['order', 'name']

    def __str__(self):
        return f'{self.app.name} / {self.name}'


class Endpoint(models.Model):
    METHOD_CHOICES = [
        ('GET', 'GET'), ('POST', 'POST'), ('PUT', 'PUT'),
        ('PATCH', 'PATCH'), ('DELETE', 'DELETE'),
    ]
    group = models.ForeignKey(EndpointGroup, related_name='endpoints', on_delete=models.CASCADE)
    method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    path = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'endpoints'
        ordering = ['order', 'path']

    def __str__(self):
        return f'{self.method} {self.path}'


class FrontendService(models.Model):
    app = models.ForeignKey(AppSpec, related_name='services', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    endpoint_groups = models.ManyToManyField(EndpointGroup, blank=True, related_name='services')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'frontend_services'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Page(models.Model):
    app = models.ForeignKey(AppSpec, related_name='pages', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    route = models.CharField(max_length=500)
    services = models.ManyToManyField(FrontendService, blank=True, related_name='pages')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'pages'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Interaction(models.Model):
    TYPE_CHOICES = [
        ('click', 'Clic'), ('form', 'Formulaire'),
        ('navigation', 'Navigation'), ('display', 'Affichage'), ('other', 'Autre'),
    ]
    page = models.ForeignKey(Page, related_name='interactions', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'interactions'
        ordering = ['order']

    def __str__(self):
        return f'{self.page.name} / {self.name}'


class Pipeline(models.Model):
    page = models.ForeignKey(Page, related_name='pipelines', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    steps = models.JSONField(default=list)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'pipelines'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name
