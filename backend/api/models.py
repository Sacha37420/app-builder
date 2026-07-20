from django.db import models


class AppSpec(models.Model):
    APP_TYPE_CHOICES = [
        ('django-angular', 'Django + Angular'),
        ('django',         'Django seul'),
        ('spring-angular', 'Spring + Angular'),
        ('spring',         'Spring seul'),
        ('angular',        'Angular seul'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    app_type = models.CharField(max_length=30, choices=APP_TYPE_CHOICES, default='django-angular')
    owner_email = models.EmailField(max_length=255, blank=True)
    # Groupes Keycloak autorisés à utiliser l'app une fois déployée (cloisonnement,
    # cf. CLAUDE.md « Sécurité — cloisonnement des applications »). Champ structuré
    # plutôt qu'une mention dans le chat : il doit survivre à un effacement du chat.
    required_groups = models.JSONField(default=list)
    # Historique de conversation IA (persisté via AppSpecChatHistoryView).
    # Présent en base depuis la migration 0003 — la colonne est NOT NULL,
    # donc le champ doit rester déclaré ici sinon tout INSERT échoue.
    chat_history = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'app_specs'
        ordering = ['-updated_at']

    def __str__(self):
        return self.name


class DataModel(models.Model):
    """Entité métier (table Django / interface TypeScript)."""
    app = models.ForeignKey(AppSpec, related_name='data_models', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)          # ex: "Produit"
    description = models.TextField(blank=True)
    # [{name, type, required, unique, max_length, default, help_text}]
    fields = models.JSONField(default=list)
    # [{name, rel_type (FK/M2M/O2O), to_model, related_name, on_delete}]
    relationships = models.JSONField(default=list)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'data_models'
        ordering = ['order', 'name']

    def __str__(self):
        return f'{self.app.name} / {self.name}'


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
    OPERATION_CHOICES = [
        ('list', 'List'), ('create', 'Create'), ('retrieve', 'Retrieve'),
        ('update', 'Update'), ('partial_update', 'Partial Update'),
        ('delete', 'Delete'), ('custom', 'Custom'),
    ]

    group = models.ForeignKey(EndpointGroup, related_name='endpoints', on_delete=models.CASCADE)
    method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    path = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    # Sémantique pour la génération de code
    operation = models.CharField(max_length=20, choices=OPERATION_CHOICES, default='custom')
    linked_model_name = models.CharField(max_length=200, blank=True)  # nom d'un DataModel
    auth_required = models.BooleanField(default=True)
    required_roles = models.JSONField(default=list)        # ex: ["admin", "editor"]
    request_schema = models.JSONField(null=True, blank=True)   # {field: type}
    response_schema = models.JSONField(null=True, blank=True)  # {field: type}
    query_params = models.JSONField(default=list)          # [{name, type, required, description}]
    steps = models.JSONField(default=list)                 # [{label, type, description}]

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
    LAYOUT_CHOICES = [
        ('list', 'Liste / tableau'), ('detail', 'Vue détail'),
        ('form', 'Formulaire'), ('dashboard', 'Dashboard'),
        ('mixed', 'Mixte'),
    ]

    app = models.ForeignKey(AppSpec, related_name='pages', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    route = models.CharField(max_length=500)
    services = models.ManyToManyField(FrontendService, blank=True, related_name='pages')
    order = models.PositiveIntegerField(default=0)

    # Sémantique pour la génération de code
    layout = models.CharField(max_length=20, choices=LAYOUT_CHOICES, default='mixed')
    # [{type (table/form/chart/card), label, linked_model, fields, config}]
    components = models.JSONField(default=list)

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


class Pipeline(models.Model):
    page = models.ForeignKey(Page, related_name='pipelines', on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # Nom de l'Interaction (même page) qui déclenche ce pipeline. Émis par l'IA
    # et affiché par le frontend ; stocké comme nom libre, pas une FK.
    trigger_interaction = models.CharField(max_length=200, blank=True)
    # [{id, label, type (trigger/service_call/transform/state_update/navigate/error),
    #   service_method, data_flow, on_error}]
    steps = models.JSONField(default=list)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'pipelines'
        ordering = ['order', 'name']
