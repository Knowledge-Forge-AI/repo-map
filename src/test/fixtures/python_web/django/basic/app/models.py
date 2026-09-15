from django.db import models


class InventoryItem(models.Model):
    name = models.CharField(max_length=64)
    active = models.BooleanField(default=True)
