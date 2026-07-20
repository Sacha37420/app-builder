from rest_framework import serializers
from .models import (
    AppSpec, DataModel, EndpointGroup, Endpoint,
    FrontendService, Page, Interaction, Pipeline,
)


class DataModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataModel
        fields = ['id', 'name', 'description', 'fields', 'relationships', 'order']


class EndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = Endpoint
        fields = [
            'id', 'method', 'path', 'description', 'order',
            'operation', 'linked_model_name', 'auth_required',
            'required_roles', 'request_schema', 'response_schema', 'query_params', 'steps',
        ]


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
    layout = serializers.CharField(max_length=50, default='mixed')
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
        ]

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
            'id', 'name', 'description', 'app_type', 'owner_email', 'required_groups',
            'created_at', 'updated_at', 'chat_history',
            'data_models', 'endpoint_groups', 'services', 'pages',
        ]
        # chat_history est exposé en lecture (pour loadSpec côté frontend) mais
        # écrit uniquement via l'endpoint dédié PATCH /api/apps/<id>/chat/,
        # pour ne pas être écrasé par l'autosave PUT de la spec complète.
        read_only_fields = ['created_at', 'updated_at', 'chat_history']

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
