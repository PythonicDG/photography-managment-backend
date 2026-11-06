from django.db import models

from accounts.ids import new_local_id


class Payment(models.Model):
    """Money received from a client for a booking."""

    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    booking = models.ForeignKey('bookings.Booking', on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    method = models.CharField(max_length=50, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.amount} on {self.date}'


class TeamPayment(models.Model):
    """Money paid out to a team member for a booking."""

    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    booking = models.ForeignKey('bookings.Booking', on_delete=models.CASCADE, related_name='team_payments')
    assignment = models.ForeignKey('bookings.TeamAssignment', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    member = models.ForeignKey('bookings.TeamMember', on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    method = models.CharField(max_length=50, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.member}: {self.amount}'


class AssistJob(models.Model):
    """A shoot where the studio helped another photographer."""

    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    studio = models.ForeignKey('accounts.Studio', on_delete=models.CASCADE, related_name='assist_jobs')
    photographer = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    event = models.CharField(max_length=150)
    date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=100, blank=True)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.event} for {self.photographer}'


class AssistPayment(models.Model):
    local_id = models.CharField(max_length=100, default=new_local_id, editable=False)
    position = models.PositiveIntegerField(default=0, editable=False)
    job = models.ForeignKey(AssistJob, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    method = models.CharField(max_length=50, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f'{self.amount} on {self.date}'
