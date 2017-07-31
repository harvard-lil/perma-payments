from django.contrib import admin
from django.contrib.auth.models import Group


from .models import SubscriptionAgreement, SubscriptionRequest

# remove builtin models
# admin.site.unregister(Site)
admin.site.unregister(Group)

## HELPERS ##

class ReadOnlyTabularInline(admin.TabularInline):
    extra = 0
    can_delete = False
    editable_fields = []
    readonly_fields = []
    exclude = []

    def get_readonly_fields(self, request, obj=None):
        return list(self.readonly_fields) + \
               [field.name for field in self.model._meta.fields
                if field.name not in self.editable_fields and
                   field.name not in self.exclude]

    def has_add_permission(self, request):
        return False


## Admin Models ##

class SubscriptionRequestInline(ReadOnlyTabularInline):
    model = SubscriptionRequest

class SubscriptionRequestAdmin(admin.ModelAdmin):
    list_display = [f.name for f in SubscriptionRequest._meta.get_fields()]

@admin.register(SubscriptionAgreement)
class SubscriptionAgreementAdmin(admin.ModelAdmin):
    readonly_fields = list_display = ('id', 'registrar', 'status', 'status_updated')
    inlines = [
        SubscriptionRequestInline,
    ]
