from django.db import models

from accounts.ids import new_local_id


class TeamMember(models.Model):
    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    studio = models.ForeignKey('accounts.Studio', on_delete=models.CASCADE, related_name='team_members')
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.role})' if self.role else self.name


class Booking(models.Model):
    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    studio = models.ForeignKey('accounts.Studio', on_delete=models.CASCADE, related_name='bookings')
    quotation = models.ForeignKey('quotations.Quotation', on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='bookings')
    event = models.CharField(max_length=150)
    date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    service_names = models.JSONField(default=list, blank=True)
    checklist = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.event} - {self.client}'


class TeamAssignment(models.Model):
    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='assignments')
    member = models.ForeignKey(TeamMember, on_delete=models.CASCADE, related_name='assignments')
    date = models.DateField(null=True, blank=True)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f'{self.member} on {self.booking}'
