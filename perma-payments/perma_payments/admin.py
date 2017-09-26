from nested_inline.admin import NestedTabularInline, NestedModelAdmin
from simple_history.admin import SimpleHistoryAdmin

from django.contrib import admin
from django.contrib.auth.models import Group, User

from .models import *

# remove builtin models
# admin.site.unregister(Site)
admin.site.unregister(Group)
admin.site.unregister(User)

# Globally disable delete selected
# admin.site.disable_action('delete_selected')

## HELPERS ##


class ReadOnlyTabularInline(NestedTabularInline):
    extra = 0
    # can_delete = False
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

class UpdateRequestResponseInline(ReadOnlyTabularInline):
    model = UpdateRequestResponse
    fk_name = 'related_request'
    exclude = ['full_response', 'polymorphic_ctype', 'response_ptr']


class UpdateRequestInline(ReadOnlyTabularInline):
    model = UpdateRequest
    fk_name = 'subscription_agreement'
    exclude = ['polymorphic_ctype', 'outgoingtransaction_ptr']
    inlines = [
        UpdateRequestResponseInline,
    ]


class SubscriptionRequestResponseInline(ReadOnlyTabularInline):
    model = SubscriptionRequestResponse
    fk_name = 'related_request'
    exclude = ['full_response', 'polymorphic_ctype', 'response_ptr']


class SubscriptionRequestInline(ReadOnlyTabularInline):
    model = SubscriptionRequest
    fk_name = 'subscription_agreement'
    exclude = ['polymorphic_ctype', 'outgoingtransaction_ptr']
    inlines = [
        SubscriptionRequestResponseInline,
    ]


@admin.register(SubscriptionAgreement)
class SubscriptionAgreementAdmin(NestedModelAdmin, SimpleHistoryAdmin):
    readonly_fields =  ('id', 'registrar', 'cancellation_requested', 'status', 'status_updated')
    list_display = ('id', 'registrar', 'cancellation_requested', 'status', 'status_updated', 'get_reference_number')
    list_filter = ('registrar', 'cancellation_requested', 'status')
    search_fields = ['registrar','subscription_request__reference_number']
    inlines = [
        SubscriptionRequestInline,
        UpdateRequestInline,
    ]

    def get_reference_number(self, obj):
        return obj.subscription_request.reference_number
    get_reference_number.short_description = 'Reference Number'
    get_reference_number.admin_order_field  = 'subscription_request__reference_number'

    # def has_delete_permission(self, request, obj=None):
    #     # Disable delete
    #     return False

    def has_add_permission(self, request, obj=None):
        # Disable manual creation of new instances
        return False

    # def save_model(self, request, obj, form, change):
    #     # Return nothing to make sure user can't update any data
    #     pass
