from django.db import models

from accounts.ids import new_local_id


class Client(models.Model):
    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    studio = models.ForeignKey('accounts.Studio', on_delete=models.CASCADE, related_name='clients')
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Enquiry(models.Model):
    STATUS_CHOICES = [('New', 'New'), ('Contacted', 'Contacted'), ('Quoted', 'Quoted'), ('Closed', 'Closed')]

    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    studio = models.ForeignKey('accounts.Studio', on_delete=models.CASCADE, related_name='enquiries')
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='enquiries')
    event = models.CharField(max_length=150)
    date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    source = models.CharField(max_length=100, blank=True)
    follow_up = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='New')

    class Meta:
        ordering = ['-date']
        verbose_name_plural = 'enquiries'

    def __str__(self):
        return f'{self.event} - {self.client}'
