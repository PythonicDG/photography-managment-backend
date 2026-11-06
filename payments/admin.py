from django.contrib import admin

from .models import AssistJob, AssistPayment, Payment, TeamPayment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('booking', 'amount', 'date', 'method', 'reference')
    list_filter = ('method', 'date')
    search_fields = ('reference', 'note', 'booking__event', 'booking__client__name')
    list_select_related = ('booking',)
    autocomplete_fields = ('booking',)
    date_hierarchy = 'date'


@admin.register(TeamPayment)
class TeamPaymentAdmin(admin.ModelAdmin):
    list_display = ('member', 'booking', 'amount', 'date', 'method')
    list_filter = ('method', 'date')
    search_fields = ('member__name', 'note', 'booking__event')
    list_select_related = ('member', 'booking')
    autocomplete_fields = ('booking', 'member')
    date_hierarchy = 'date'


class AssistPaymentInline(admin.TabularInline):
    model = AssistPayment
    extra = 0


@admin.register(AssistJob)
class AssistJobAdmin(admin.ModelAdmin):
    list_display = ('event', 'photographer', 'studio', 'role', 'date', 'fee', 'paid', 'due_date')
    list_filter = ('date', 'due_date')
    search_fields = ('event', 'photographer', 'phone', 'studio__name')
    list_select_related = ('studio',)
    autocomplete_fields = ('studio',)
    date_hierarchy = 'date'
    inlines = (AssistPaymentInline,)

    @admin.display(description='Paid')
    def paid(self, obj):
        return sum(p.amount for p in obj.payments.all())


@admin.register(AssistPayment)
class AssistPaymentAdmin(admin.ModelAdmin):
    list_display = ('job', 'amount', 'date', 'method')
    list_filter = ('method', 'date')
    search_fields = ('job__event', 'job__photographer', 'note')
    autocomplete_fields = ('job',)
