#
# ========================================================
# Copyright (c) 2012 Whamcloud, Inc.  All rights reserved.
# ========================================================


from chroma_core.models import PowerControlType, PowerControlDevice, PowerControlDeviceOutlet
from chroma_api.authentication import AnonymousAuthentication
from chroma_api.utils import CustomModelResource

from django.forms import ModelForm, ModelChoiceField

from tastypie.authorization import DjangoAuthorization
from tastypie.validation import FormValidation
from tastypie import fields


class ResolvingFormValidation(FormValidation):
    """
    Enhance Tastypie's built-in FormValidation to do resolution of
    incoming resource_uri values to PKs. This seems like it ought to
    be part of Tastypie, oh well.
    """
    def _resolve_uri_to_pk(self, uri):
        from django.core.urlresolvers import resolve

        if not uri:
            return None

        if not isinstance(uri, basestring):
            # Handle lists of URIs
            return [resolve(u)[2]['pk'] for u in uri]
        else:
            # This is the normal case, where we've received a string that
            # looks like "/api/foo/1/", and we need to resolve that into
            # "1".
            return resolve(uri)[2]['pk']

    def _resolve_relation_uris(self, data):
        # We should be working on a copy of the data, since we're
        # modifying it (FormValidation promises not to modify the bundle).
        data = data.copy()

        fields_to_resolve = [k for k, v in self.form_class.base_fields.items()
                             if issubclass(v.__class__, ModelChoiceField)]

        for field in fields_to_resolve:
            if field in data:
                data[field] = self._resolve_uri_to_pk(data[field])

        return data

    # This is pretty much a straight copy of FormValidation's is_valid().
    # It's unfortunate that there's not a cleaner place to hook into the
    # validation processing for subclasses.
    def is_valid(self, bundle, request=None):
        """
        Performs a check on ``bundle.data``to ensure it is valid.

        If the form is valid, an empty list (all valid) will be returned. If
        not, a list of errors will be returned.
        """
        data = bundle.data

        if not request:
            raise RuntimeError("Must be used with an incoming request")

        # Ensure we get a bound Form, regardless of the state of the bundle.
        if data is None:
            data = {}

        # FormValidation doesn't understand URIs in bundle fields --
        # we need to resolve them into primary keys for the validation
        # to work properly.
        data = self._resolve_relation_uris(data)

        form = self.form_class(data)

        if form.is_valid():
            return {}

        # The data is invalid. Let's collect all the error messages & return
        # them.
        return form.errors


class PowerControlTypeForm(ModelForm):
    class Meta:
        model = PowerControlType


class PowerControlTypeResource(CustomModelResource):
    """
    A type (make/model, etc.) of power control device
    """
    name = fields.CharField(attribute = 'display_name', readonly = True)

    class Meta:
        queryset = PowerControlType.objects.all()
        resource_name = 'power_control_type'
        authorization = DjangoAuthorization()
        authentication = AnonymousAuthentication()
        validation = ResolvingFormValidation(form_class=PowerControlTypeForm)
        ordering = ['name', 'make', 'model']
        filtering = {'name': ['exact'], 'make': ['exact']}
        list_allowed_methods = ['get', 'post']
        detail_allowed_methods = ['get', 'put', 'delete']
        readonly = ['id']
        always_return_data = True


class PowerControlDeviceForm(ModelForm):
    class Meta:
        model = PowerControlDevice

    def _clean_fields(self):
        super(PowerControlDeviceForm, self)._clean_fields()

        # Django, we need to talk. If you tell me I'll have the chance to
        # do custom validation and modify attributes in my model's clean(),
        # then WHY DO YOU DELETE THE VALUE BEFORE I'VE HAD A CHANCE TO FIX IT?!?
        if 'address' in self._errors:
            del self._errors['address']
            field = self.fields['address']
            self.cleaned_data['address'] = field.widget.value_from_datadict(self.data, self.files, self.add_prefix('address'))


class PowerControlDeviceResource(CustomModelResource):
    """
    An instance of a power control device, associated with a power control type
    """
    device_type = fields.ToOneField('chroma_api.power_control.PowerControlTypeResource', 'device_type', full = True)
    outlets = fields.ToManyField('chroma_api.power_control.PowerControlDeviceOutletResource', 'outlets', full = True, null = True)

    class Meta:
        queryset = PowerControlDevice.objects.all()
        resource_name = 'power_control_device'
        authorization = DjangoAuthorization()
        authentication = AnonymousAuthentication()
        validation = ResolvingFormValidation(form_class=PowerControlDeviceForm)
        ordering = ['name']
        filtering = {'name': ['exact']}
        list_allowed_methods = ['get', 'post']
        detail_allowed_methods = ['get', 'put', 'delete']
        readonly = ['id']
        always_return_data = True


class PowerControlDeviceOutletForm(ModelForm):
    class Meta:
        model = PowerControlDeviceOutlet


class PowerControlDeviceOutletResource(CustomModelResource):
    """
    An outlet (individual host power control entity) associated with a
    Power Control Device.
    """
    device = fields.ToOneField('chroma_api.power_control.PowerControlDeviceResource', 'device')
    host = fields.ToOneField('chroma_api.host.HostResource', 'host', null = True)

    class Meta:
        queryset = PowerControlDeviceOutlet.objects.all()
        resource_name = 'power_control_device_outlet'
        authorization = DjangoAuthorization()
        authentication = AnonymousAuthentication()
        validation = ResolvingFormValidation(form_class=PowerControlDeviceOutletForm)
        list_allowed_methods = ['get', 'post']
        detail_allowed_methods = ['get', 'put', 'delete', 'patch']
        readonly = ['id']
        always_return_data = True
