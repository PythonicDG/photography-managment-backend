from django.db import models

from accounts.ids import new_local_id


class Service(models.Model):
    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    studio = models.ForeignKey('accounts.Studio', on_delete=models.CASCADE, related_name='services')
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Package(models.Model):
    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    studio = models.ForeignKey('accounts.Studio', on_delete=models.CASCADE, related_name='packages')
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    services = models.ManyToManyField(Service, blank=True, related_name='packages')
    team = models.JSONField(default=list, blank=True, help_text='Crew covered, e.g. ["1 Traditional Photographer"]')
    deliverables = models.JSONField(default=list, blank=True, help_text='What the client receives')
    notes = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
