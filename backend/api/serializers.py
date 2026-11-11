from rest_framework import serializers
from . import conformite
from .models import (
    AppSpec, DataModel, EndpointGroup, Endpoint,
    FrontendService, Page, Interaction, Pipeline,
)


class DataModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataModel
        fields = ['id', 'name', 'description', 'fields', 'relationships', 'order',
                  'kind', 'access', 'states', 'constraints']

    def validate_kind(self, value):
        if value not in conformite.GENRES_DE_MODELE:
            raise serializers.ValidationError(
                f'Genre de modèle « {value} » inconnu : ' + ', '.join(conformite.GENRES_DE_MODELE) + '.')
        return value

    def validate_access(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Objet attendu (`{}` = accès non décrit).')
        return value

    def validate_states(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Objet attendu (`{}` = aucune machine à états).')
        return value

    def validate_constraints(self, value):
        if not isinstance(value, list) or not all(isinstance(c, dict) for c in value):
            raise serializers.ValidationError('Liste de contraintes attendue.')
        return value


class EndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = Endpoint
        fields = [
            'id', 'method', 'path', 'description', 'order',
            'operation', 'linked_model_name', 'auth_required', 'public_reason',
            'required_roles', 'request_schema', 'response_schema', 'query_params', 'steps', 'auth',
        ]

    def validate_auth(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Objet attendu (`{}` = jeton du lab).')
        mode = value.get('mode')
        if mode not in (None, '') and mode not in conformite.MODES_AUTH:
            raise serializers.ValidationError(
                f'Mode « {mode} » inconnu : ' + ', '.join(conformite.MODES_AUTH) + '.')
        return value

    def validate(self, attrs):
        # Règle de cohérence I1 : un mode autre que le jeton du lab rend la route
        # « sans jeton » (avec la raison) ; une route sans jeton sans mode est publique.
        auth = attrs.get('auth')
        if isinstance(auth, dict) and auth.get('mode') not in (None, '', 'jwt'):
            attrs['auth_required'] = False
            if isinstance(auth.get('reason'), str) and auth['reason'].strip():
                attrs['public_reason'] = auth['reason'].strip()
        elif attrs.get('auth_required') is False and not auth:
            attrs['auth'] = {'mode': 'public'}
        return attrs


class EndpointGroupSerializer(serializers.ModelSerializer):
    endpoints = EndpointSerializer(many=True, required=False)

    class Meta:
        model = EndpointGroup
        fields = ['id', 'name', 'description', 'order', 'endpoints']

    def create(self, validated_data):
        endpoints_data = validated_data.pop('endpoints', [])
        group = EndpointGroup.objects.create(**validated_data)
        for ep in endpoints_data:
            Endpoint.objects.create(group=group, **ep)
        return group

    def update(self, instance, validated_data):
        endpoints_data = validated_data.pop('endpoints', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if endpoints_data is not None:
            instance.endpoints.all().delete()
            for ep in endpoints_data:
                Endpoint.objects.create(group=instance, **ep)
        return instance


class InteractionSerializer(serializers.ModelSerializer):
    # CharField sans choices pour accepter n'importe quel type généré par l'IA
    type = serializers.CharField(max_length=50)

    class Meta:
        model = Interaction
        fields = ['id', 'name', 'type', 'description', 'order']


class PipelineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pipeline
        fields = ['id', 'name', 'description', 'trigger_interaction', 'steps', 'order']


class FrontendServiceSerializer(serializers.ModelSerializer):
    # ListField au lieu de PrimaryKeyRelatedField : accepte des IDs négatifs (temporaires)
    endpoint_group_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )

    class Meta:
        model = FrontendService
        fields = ['id', 'name', 'order', 'endpoint_group_ids']

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        # Remplace les IDs temporaires par les vrais IDs de la M2M
        rep['endpoint_group_ids'] = list(instance.endpoint_groups.values_list('id', flat=True))
        return rep

    def create(self, validated_data):
        group_ids = validated_data.pop('endpoint_group_ids', [])
        svc = FrontendService.objects.create(**validated_data)
        svc.endpoint_groups.set(EndpointGroup.objects.filter(id__in=group_ids))
        return svc

    def update(self, instance, validated_data):
        group_ids = validated_data.pop('endpoint_group_ids', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if group_ids is not None:
            instance.endpoint_groups.set(EndpointGroup.objects.filter(id__in=group_ids))
        return instance


class PageSerializer(serializers.ModelSerializer):
    # CharField sans choices pour accepter kanban, calendar, grid, progress, public…
    # max_length = celui de la colonne pages.layout (20) : au-delà, PostgreSQL
    # refusait l'écriture et l'API répondait 500 au lieu de 400.
    layout = serializers.CharField(max_length=20, default='mixed')
    interactions = InteractionSerializer(many=True, required=False)
    pipelines = PipelineSerializer(many=True, required=False)
    # Même raison que endpoint_group_ids : accepte des IDs temporaires négatifs
    service_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )

    class Meta:
        model = Page
        fields = [
            'id', 'name', 'route', 'order', 'layout', 'components',
            'service_ids', 'interactions', 'pipelines',
            'public', 'public_reason', 'required_roles',
        ]

    def validate_required_roles(self, value):
        if not isinstance(value, list) or not all(isinstance(r, str) for r in value):
            raise serializers.ValidationError('Liste de noms de rôles attendue.')
        return value

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['service_ids'] = list(instance.services.values_list('id', flat=True))
        return rep

    def create(self, validated_data):
        interactions_data = validated_data.pop('interactions', [])
        pipelines_data = validated_data.pop('pipelines', [])
        service_ids = validated_data.pop('service_ids', [])
        page = Page.objects.create(**validated_data)
        page.services.set(FrontendService.objects.filter(id__in=service_ids))
        for inter in interactions_data:
            Interaction.objects.create(page=page, **inter)
        for pipe in pipelines_data:
            Pipeline.objects.create(page=page, **pipe)
        return page

    def update(self, instance, validated_data):
        interactions_data = validated_data.pop('interactions', None)
        pipelines_data = validated_data.pop('pipelines', None)
        service_ids = validated_data.pop('service_ids', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if service_ids is not None:
            instance.services.set(FrontendService.objects.filter(id__in=service_ids))
        if interactions_data is not None:
            instance.interactions.all().delete()
            for inter in interactions_data:
                Interaction.objects.create(page=instance, **inter)
        if pipelines_data is not None:
            instance.pipelines.all().delete()
            for pipe in pipelines_data:
                Pipeline.objects.create(page=instance, **pipe)
        return instance


class AppSpecSerializer(serializers.ModelSerializer):
    data_models = DataModelSerializer(many=True, required=False)
    endpoint_groups = EndpointGroupSerializer(many=True, required=False)
    services = FrontendServiceSerializer(many=True, required=False)
    pages = PageSerializer(many=True, required=False)

    class Meta:
        model = AppSpec
        fields = [
            'id', 'name', 'project_name', 'description', 'app_type', 'owner_email', 'required_groups',
            'business_rules', 'uses_email',
            'roles', 'jobs', 'integrations', 'external_apis', 'extensions',
            'created_at', 'updated_at', 'chat_history',
            'data_models', 'endpoint_groups', 'services', 'pages',
        ]
        # chat_history est exposé en lecture (pour loadSpec côté frontend) mais
        # écrit uniquement via l'endpoint dédié PATCH /api/apps/<id>/chat/,
        # pour ne pas être écrasé par l'autosave PUT de la spec complète.
        # owner_email n'est jamais écrit par le client : il est posé par le
        # serveur à la création (AppSpecListCreateView.perform_create). Sans
        # cela, un PATCH déposait sa spécification dans le catalogue d'un autre.
        read_only_fields = ['created_at', 'updated_at', 'chat_history', 'owner_email']

    # ── Conformité au cadriciel du lab (api/conformite.py) ─────────────────────
    # Ce qui est refusé ici ne peut plus ENTRER dans une spécification. Ce qui s'y
    # trouvait déjà (type Spring, champ `file`) reste enregistrable tel quel, sinon
    # une spec ancienne ne pourrait plus être modifiée ; elle n'est simplement pas
    # « prête » tant que ce n'est pas corrigé.

    def validate_project_name(self, value):
        value = (value or '').strip()
        if value and conformite.erreur_nom_de_projet(value):
            raise serializers.ValidationError(conformite.erreur_nom_de_projet(value))
        return value

    def validate_app_type(self, value):
        if value in conformite.TYPES_CONSTRUCTIBLES:
            return value
        if self.instance is not None and self.instance.app_type == value:
            return value
        raise serializers.ValidationError(
            f'Type « {value} » refusé : le lab crée des apps '
            + ', '.join(conformite.TYPES_CONSTRUCTIBLES) + '.')

    def validate_required_groups(self, value):
        if not isinstance(value, list) or not all(isinstance(g, str) for g in value):
            raise serializers.ValidationError('Liste de noms de groupes attendue.')
        vus = []
        for g in (g.strip() for g in value):
            if g and g not in vus:
                vus.append(g)
        return vus

    def validate_business_rules(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Liste de règles attendue.')
        regles = []
        for r in value:
            if not isinstance(r, dict) or not isinstance(r.get('title'), str) or not r['title'].strip():
                raise serializers.ValidationError('Chaque règle est un objet avec un titre (`title`).')
            description = r.get('description')
            regle = {'title': r['title'].strip()[:200],
                     'description': description.strip() if isinstance(description, str) else ''}
            # Clés I1 (facultatives) : gardées seulement si présentes et bien typées.
            for cle in ('applies_to', 'kind'):
                if isinstance(r.get(cle), str) and r[cle].strip():
                    regle[cle] = r[cle].strip()
            if isinstance(r.get('enforced_by'), list):
                regle['enforced_by'] = [e.strip() for e in r['enforced_by'] if isinstance(e, str) and e.strip()]
            regles.append(regle)
        return regles

    @staticmethod
    def _liste_nommee(value, cle='name', quoi='élément'):
        if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
            raise serializers.ValidationError(f'Liste de {quoi}s attendue.')
        for x in value:
            if not isinstance(x.get(cle), str) or not x[cle].strip():
                raise serializers.ValidationError(f'Chaque {quoi} porte `{cle}`.')
        return value

    def validate_roles(self, value):
        self._liste_nommee(value, quoi='rôle')
        for r in value:
            if r.get('kind') not in (None, '') and r['kind'] not in conformite.GENRES_DE_ROLE:
                raise serializers.ValidationError(f"Rôle « {r['name']} » : genre « {r['kind']} » inconnu.")
        return value

    def validate_jobs(self, value):
        self._liste_nommee(value, quoi='tâche')
        for j in value:
            if j.get('kind') not in (None, '') and j['kind'] not in conformite.GENRES_DE_JOB:
                raise serializers.ValidationError(f"Tâche « {j['name']} » : genre « {j['kind']} » inconnu.")
        return value

    def validate_integrations(self, value):
        self._liste_nommee(value, cle='type', quoi='intégration')
        for i in value:
            if i['type'] not in conformite.INTEGRATIONS:
                raise serializers.ValidationError(
                    f"Intégration « {i['type']} » inconnue : le lab fournit " + ', '.join(conformite.INTEGRATIONS) + '.')
        return value

    def validate_external_apis(self, value):
        return self._liste_nommee(value, quoi='API externe')

    def validate_extensions(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Objet attendu : {data_io: [...], realtime: [...], ...}.')
        for liste, elements in value.items():
            if liste not in conformite.LISTES_D_EXTENSIONS:
                raise serializers.ValidationError(
                    f'Liste d\'extensions « {liste} » inconnue : ' + ', '.join(conformite.LISTES_D_EXTENSIONS) + '.')
            if not isinstance(elements, list) or not all(isinstance(x, dict) for x in elements):
                raise serializers.ValidationError(f'`{liste}` : liste d\'objets attendue.')
        return value

    def validate_data_models(self, value):
        # `fields` est un JSON libre : on n'y contrôle que le type « fichier ».
        deja = set()
        if self.instance is not None and not self.context.get('restauration'):
            deja = {(m.name, f.get('name')) for m in self.instance.data_models.all()
                    for f in m.fields if isinstance(f, dict) and f.get('type') == conformite.TYPE_FICHIER_ANCIEN}
        for modele in value:
            for champ in modele.get('fields') or []:
                if not isinstance(champ, dict) or champ.get('type') != conformite.TYPE_FICHIER_ANCIEN:
                    continue
                if self.context.get('restauration') or (modele.get('name'), champ.get('name')) in deja:
                    continue
                raise serializers.ValidationError(
                    f"Champ « {modele.get('name')}.{champ.get('name')} » : le type « file » n'est plus accepté. "
                    "Un fichier d'utilisateur est déposé dans le service storage du lab : utilisez le type "
                    '« storage_file » (le modèle garde le chemin).')
        return value

    # ── Helpers de résolution des IDs temporaires ──────────────────────────────

    def _build_groups(self, app, groups_data, raw_groups):
        """Crée les groupes et retourne un dict {client_id → EndpointGroup}."""
        group_id_map = {}
        for i, g in enumerate(groups_data):
            client_id = raw_groups[i].get('id') if i < len(raw_groups) else None
            endpoints_data = g.pop('endpoints', [])
            group = EndpointGroup.objects.create(app=app, **g)
            for ep in endpoints_data:
                Endpoint.objects.create(group=group, **ep)
            if client_id is not None:
                try:
                    group_id_map[int(client_id)] = group
                except (ValueError, TypeError):
                    pass
        return group_id_map

    def _build_services(self, app, services_data, raw_services, group_id_map):
        """Crée les services et retourne un dict {client_id → FrontendService}."""
        svc_id_map = {}
        for i, s in enumerate(services_data):
            client_id = raw_services[i].get('id') if i < len(raw_services) else None
            raw_gids = s.pop('endpoint_group_ids', [])
            real_groups = [group_id_map[gid] for gid in raw_gids if gid in group_id_map]
            svc = FrontendService.objects.create(app=app, **s)
            svc.endpoint_groups.set(real_groups)
            if client_id is not None:
                try:
                    svc_id_map[int(client_id)] = svc
                except (ValueError, TypeError):
                    pass
        return svc_id_map

    def _build_pages(self, app, pages_data, raw_pages, svc_id_map):
        """Crée les pages avec leurs services, interactions et pipelines."""
        for i, p in enumerate(pages_data):
            interactions_data = p.pop('interactions', [])
            pipelines_data = p.pop('pipelines', [])
            raw_sids = p.pop('service_ids', [])
            real_services = [svc_id_map[sid] for sid in raw_sids if sid in svc_id_map]
            page = Page.objects.create(app=app, **p)
            page.services.set(real_services)
            for inter in interactions_data:
                Interaction.objects.create(page=page, **inter)
            for pipe in pipelines_data:
                Pipeline.objects.create(page=page, **pipe)

    # ── Create / Update ────────────────────────────────────────────────────────

    def create(self, validated_data):
        data_models_data = validated_data.pop('data_models', [])
        groups_data = validated_data.pop('endpoint_groups', [])
        services_data = validated_data.pop('services', [])
        pages_data = validated_data.pop('pages', [])
        app = AppSpec.objects.create(**validated_data)

        raw = self.initial_data
        for dm in data_models_data:
            DataModel.objects.create(app=app, **dm)

        group_id_map = self._build_groups(app, groups_data, raw.get('endpoint_groups') or [])
        svc_id_map   = self._build_services(app, services_data, raw.get('services') or [], group_id_map)
        self._build_pages(app, pages_data, raw.get('pages') or [], svc_id_map)
        return app

    def update(self, instance, validated_data):
        data_models_data = validated_data.pop('data_models', None)
        groups_data      = validated_data.pop('endpoint_groups', None)
        services_data    = validated_data.pop('services', None)
        pages_data       = validated_data.pop('pages', None)

        raw = self.initial_data

        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()

        if data_models_data is not None:
            instance.data_models.all().delete()
            for dm in data_models_data:
                DataModel.objects.create(app=instance, **dm)

        group_id_map = {}
        if groups_data is not None:
            instance.endpoint_groups.all().delete()
            group_id_map = self._build_groups(instance, groups_data, raw.get('endpoint_groups') or [])

        svc_id_map = {}
        if services_data is not None:
            instance.services.all().delete()
            svc_id_map = self._build_services(instance, services_data, raw.get('services') or [], group_id_map)

        if pages_data is not None:
            instance.pages.all().delete()
            self._build_pages(instance, pages_data, raw.get('pages') or [], svc_id_map)

        return instance
