"""
Auto-create Profile rows.

Every view/template touches ``user.profile`` (role checks, display name).
Creating it here at User creation time removes a whole class of
RelatedObjectDoesNotExist failures for users made via ``createsuperuser`` or
the admin.
"""
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.accounts.models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
