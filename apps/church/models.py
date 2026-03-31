"""Models for church domain."""

from django.db import models


class Plan(models.Model):
    """Subscription plan available to churches."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    max_members = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "plans"
        ordering = ["name"]  # noqa: RUF012

    def __str__(self) -> str:
        return self.name


class Gateway(models.Model):
    """Payment gateway configuration."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gateways"
        ordering = ["name"]  # noqa: RUF012

    def __str__(self) -> str:
        return self.name


class Church(models.Model):
    """Represents an InChurch customer (church organization)."""

    external_id = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    country = models.CharField(max_length=50, default="BR")
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name="churches")
    gateway = models.ForeignKey(Gateway, on_delete=models.SET_NULL, null=True, blank=True, related_name="churches")
    is_active = models.BooleanField(default=True, db_index=True)
    hubspot_company_id = models.CharField(max_length=50, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "churches"
        ordering = ["name"]  # noqa: RUF012
        indexes = [  # noqa: RUF012
            models.Index(fields=["is_active", "country"]),
        ]

    def __str__(self) -> str:
        return self.name
