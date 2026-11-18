"""DRF integration for ODM models.

ODMSerializer: a plain Serializer with ModelSerializer-like create()/update().
ODMModelViewSet: ModelViewSet whose get_queryset() always returns a fresh queryset
(DRF only re-clones Django QuerySets, so a class-level ODM queryset would otherwise keep
its evaluated result between requests).
"""
from rest_framework import serializers, viewsets


class ODMSerializer(serializers.Serializer):
    def get_fields(self):
        # Like ModelSerializer: Meta.fields decides which fields exist and in what order.
        fields = super().get_fields()
        order = getattr(getattr(self, 'Meta', None), 'fields', None)
        if order and order != '__all__':
            return {name: fields[name] for name in order}
        return fields

    def _split_m2m(self, validated_data):
        model = self.Meta.model
        m2m = {}
        for field in model._meta.fields:
            if field.many_to_many and field.name in validated_data:
                m2m[field.name] = validated_data.pop(field.name)
        return m2m

    def create(self, validated_data):
        m2m = self._split_m2m(validated_data)
        instance = self.Meta.model.objects.create(**validated_data)
        for name, value in m2m.items():
            getattr(instance, name).set(value)
        return instance

    def update(self, instance, validated_data):
        m2m = self._split_m2m(validated_data)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        for name, value in m2m.items():
            getattr(instance, name).set(value)
        return instance


class ODMModelViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        return self.queryset.all()
