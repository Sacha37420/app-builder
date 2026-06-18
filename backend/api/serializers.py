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
            'required_roles', 'request_schema', 'response_schema', 'query_params',
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
    class Meta:
        model = Interaction
        fields = ['id', 'name', 'type', 'description', 'order']


class PipelineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pipeline
        fields = ['id', 'name', 'description', 'steps', 'order']


class FrontendServiceSerializer(serializers.ModelSerializer):
    endpoint_group_ids = serializers.PrimaryKeyRelatedField(
        many=True, source='endpoint_groups',
        queryset=EndpointGroup.objects.all(), required=False,
    )

    class Meta:
        model = FrontendService
        fields = ['id', 'name', 'order', 'endpoint_group_ids']

    def create(self, validated_data):
        groups = validated_data.pop('endpoint_groups', [])
        svc = FrontendService.objects.create(**validated_data)
        svc.endpoint_groups.set(groups)
        return svc

    def update(self, instance, validated_data):
        groups = validated_data.pop('endpoint_groups', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if groups is not None:
            instance.endpoint_groups.set(groups)
        return instance


class PageSerializer(serializers.ModelSerializer):
    interactions = InteractionSerializer(many=True, required=False)
    pipelines = PipelineSerializer(many=True, required=False)
    service_ids = serializers.PrimaryKeyRelatedField(
        many=True, source='services',
        queryset=FrontendService.objects.all(), required=False,
    )

    class Meta:
        model = Page
        fields = [
            'id', 'name', 'route', 'order', 'layout', 'components',
            'service_ids', 'interactions', 'pipelines',
        ]

    def create(self, validated_data):
        interactions_data = validated_data.pop('interactions', [])
        pipelines_data = validated_data.pop('pipelines', [])
        services = validated_data.pop('services', [])
        page = Page.objects.create(**validated_data)
        page.services.set(services)
        for inter in interactions_data:
            Interaction.objects.create(page=page, **inter)
        for pipe in pipelines_data:
            Pipeline.objects.create(page=page, **pipe)
        return page

    def update(self, instance, validated_data):
        interactions_data = validated_data.pop('interactions', None)
        pipelines_data = validated_data.pop('pipelines', None)
        services = validated_data.pop('services', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if services is not None:
            instance.services.set(services)
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
            'id', 'name', 'description', 'owner_email',
            'created_at', 'updated_at',
            'data_models', 'endpoint_groups', 'services', 'pages',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def _create_nested(self, app, groups_data, services_data, pages_data, data_models_data):
        for dm in data_models_data:
            DataModel.objects.create(app=app, **dm)

        group_objs = {}
        for g in groups_data:
            endpoints_data = g.pop('endpoints', [])
            group = EndpointGroup.objects.create(app=app, **g)
            for ep in endpoints_data:
                Endpoint.objects.create(group=group, **ep)
            group_objs[group.id] = group

        svc_objs = {}
        for s in services_data:
            groups = s.pop('endpoint_groups', [])
            svc = FrontendService.objects.create(app=app, **s)
            svc.endpoint_groups.set(groups)
            svc_objs[svc.id] = svc

        for p in pages_data:
            interactions_data = p.pop('interactions', [])
            pipelines_data = p.pop('pipelines', [])
            services = p.pop('services', [])
            page = Page.objects.create(app=app, **p)
            page.services.set(services)
            for inter in interactions_data:
                Interaction.objects.create(page=page, **inter)
            for pipe in pipelines_data:
                Pipeline.objects.create(page=page, **pipe)

    def create(self, validated_data):
        data_models_data = validated_data.pop('data_models', [])
        groups_data = validated_data.pop('endpoint_groups', [])
        services_data = validated_data.pop('services', [])
        pages_data = validated_data.pop('pages', [])
        app = AppSpec.objects.create(**validated_data)
        self._create_nested(app, groups_data, services_data, pages_data, data_models_data)
        return app

    def update(self, instance, validated_data):
        data_models_data = validated_data.pop('data_models', None)
        groups_data = validated_data.pop('endpoint_groups', None)
        services_data = validated_data.pop('services', None)
        pages_data = validated_data.pop('pages', None)

        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()

        if data_models_data is not None:
            instance.data_models.all().delete()
            for dm in data_models_data:
                DataModel.objects.create(app=instance, **dm)

        if groups_data is not None:
            instance.endpoint_groups.all().delete()
            for g in groups_data:
                endpoints_data = g.pop('endpoints', [])
                group = EndpointGroup.objects.create(app=instance, **g)
                for ep in endpoints_data:
                    Endpoint.objects.create(group=group, **ep)

        if services_data is not None:
            instance.services.all().delete()
            for s in services_data:
                groups = s.pop('endpoint_groups', [])
                svc = FrontendService.objects.create(app=instance, **s)
                svc.endpoint_groups.set(groups)

        if pages_data is not None:
            instance.pages.all().delete()
            for p in pages_data:
                interactions_data = p.pop('interactions', [])
                pipelines_data = p.pop('pipelines', [])
                services = p.pop('services', [])
                page = Page.objects.create(app=instance, **p)
                page.services.set(services)
                for inter in interactions_data:
                    Interaction.objects.create(page=page, **inter)
                for pipe in pipelines_data:
                    Pipeline.objects.create(page=page, **pipe)

        return instance
