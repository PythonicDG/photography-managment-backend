from decimal import Decimal

from django.db import models
from django.utils import timezone

from accounts.ids import new_local_id


class Quotation(models.Model):
    STATUS_CHOICES = [(s, s) for s in ('Draft', 'Pending', 'Accepted', 'Rejected', 'Changes requested', 'Superseded')]

    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    studio = models.ForeignKey('accounts.Studio', on_delete=models.CASCADE, related_name='quotations')
    number = models.CharField(max_length=50)
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='quotations')
    enquiry = models.ForeignKey('clients.Enquiry', on_delete=models.SET_NULL, null=True, blank=True, related_name='quotations')
    package = models.ForeignKey('catalog.Package', on_delete=models.SET_NULL, null=True, blank=True, related_name='quotations')
    event = models.CharField(max_length=150)
    date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    items = models.JSONField(default=list, blank=True, help_text='[{"name": "...", "price": 0}]')
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    advance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    terms = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Draft')
    root = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='revisions')
    version = models.PositiveIntegerField(default=1)
    feedback = models.TextField(blank=True)
    package_details = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.number} v{self.version}'

    @property
    def subtotal(self):
        total = sum((Decimal(str(i.get('price', 0))) for i in self.items or []), Decimal(0))
        if self.pk:
            total += sum((p.price for p in self.packages.all() if p.count_in_total), Decimal(0))
        return total

    @property
    def total(self):
        return self.subtotal - self.discount

    @property
    def balance(self):
        return self.total - self.advance


class QuotationPackage(models.Model):
    """Private copy of a catalogue package stored on a quotation."""

    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name='packages')
    source = models.ForeignKey('catalog.Package', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    title = models.CharField(max_length=150)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    count_in_total = models.BooleanField(default=True, help_text='Unticked packages are shown as options but left out of the total.')
    team = models.JSONField(default=list, blank=True, help_text='[{"qty": 1, "role": "..."}]')
    materials = models.JSONField(default=list, blank=True)
    gift = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.title
