from nested_inline.admin import NestedTabularInline, NestedModelAdmin
from simple_history.admin import SimpleHistoryAdmin

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import Group, User

from .models import (
    SubscriptionAgreement,
    SubscriptionRequest,
    UpdateRequest,
    ChangeRequest,
    SubscriptionRequestResponse,
    UpdateRequestResponse,
    ChangeRequestResponse,
)

# remove builtin models
# admin.site.unregister(Site)
admin.site.unregister(Group)
admin.site.unregister(User)

if settings.READONLY_ADMIN:
    # Globally disable delete selected
    admin.site.disable_action('delete_selected')

## HELPERS ##


class ReadOnlyTabularInline(NestedTabularInline):
    extra = 0
    editable_fields = []
    readonly_fields = []
    exclude = []
    if settings.READONLY_ADMIN:
        can_delete = False

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


class ChangeRequestResponseInline(ReadOnlyTabularInline):
    model = ChangeRequestResponse
    fk_name = 'related_request'
    exclude = ['full_response', 'polymorphic_ctype', 'response_ptr']


class ChangeRequestInline(ReadOnlyTabularInline):
    model = ChangeRequest
    fk_name = 'subscription_agreement'
    exclude = ['polymorphic_ctype', 'outgoingtransaction_ptr']
    inlines = [
        ChangeRequestResponseInline,
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
    # If you need fields to be editable, but want to keep this order,
    # duplicate the tuple that is currently 'readonly_fields' as 'fields'.
    # Then, remove the field you want to be editable from readonly_fields.
    # N.B. settings.READONLY_ADMIN must also be set to False for alterations to work.
    readonly_fields =  ('id', 'customer_type', 'customer_pk', 'cancellation_requested', 'status', 'updated_date', 'created_date', 'paid_through', 'current_link_limit', 'current_rate', 'current_frequency')
    list_display = ('id', 'customer_type', 'customer_pk', 'cancellation_requested', 'status', 'updated_date', 'get_reference_number')
    list_filter = ('customer_type', 'customer_pk', 'cancellation_requested', 'status')
    search_fields = ['customer_type', 'customer_pk','subscription_request__reference_number']
    inlines = [
        SubscriptionRequestInline,
        ChangeRequestInline,
        UpdateRequestInline,
    ]

    def get_reference_number(self, obj):
        return obj.subscription_request.reference_number
    get_reference_number.short_description = 'Reference Number'
    get_reference_number.admin_order_field  = 'subscription_request__reference_number'

    if settings.READONLY_ADMIN:
        def has_delete_permission(self, request, obj=None):
            # Disable delete
            return False

    def has_add_permission(self, request, obj=None):
        # Disable manual creation of new instances
        return False

    if settings.READONLY_ADMIN:
        def save_model(self, request, obj, form, change):
            # Return nothing to make sure user can't update any data
            pass
