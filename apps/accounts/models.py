"""
User profiles and roles.

Role semantics (see docs/ARCHITECTURE.md):

* admin     — full access incl. deleting user data. **Cannot read private
              annotations** (privacy decision, see prompt's Roles note).
* librarian — books, metadata, collections, room moderation.
* member    — browse, read, bookmark, review, private annotations, rooms.
"""
from django.conf import settings
from django.db import models


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    LIBRARIAN = "librarian", "Librarian"
    MEMBER = "member", "Member"


class LayerPreference(models.TextChoices):
    PRIVATE = "private", "Private"
    ROOM = "room", "Room"


class Profile(models.Model):
    """Per-user settings and role. One row per auth.User."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    display_name = models.CharField(max_length=120, blank=True)
    avatar = models.CharField(max_length=255, blank=True)  # storage key, never blob
    theme = models.CharField(max_length=16, default="auto")  # auto|light|dark
    default_layer = models.CharField(
        max_length=8, choices=LayerPreference.choices, default=LayerPreference.PRIVATE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["role"])]

    def __str__(self) -> str:
        return self.display_name or self.user.get_username()

    # -- role helpers (server-side authority; never trust the client) --------
    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_librarian(self) -> bool:
        return self.role in {Role.LIBRARIAN, Role.ADMIN}

    def can_manage_library(self) -> bool:
        """Upload/edit books, metadata, collections."""
        return self.is_librarian

    def can_moderate_rooms(self) -> bool:
        return self.is_librarian

    def can_delete_user_data(self) -> bool:
        return self.is_admin

    @property
    def label(self) -> str:
        """Author label shown in the viewer; server-known display name."""
        return self.display_name or self.user.get_username()


def profile_for(user) -> Profile:
    """Fetch (or lazily create) the profile for a user.

    Always returns the current row and keeps the reverse OneToOne cache in
    sync — constructing Profile(user=…) caches the relation, so a later
    update written through a different instance would otherwise leave
    ``user.profile`` stale for the rest of the request.
    """
    if not user.is_authenticated:
        raise ValueError("profile_for requires an authenticated user")
    profile, _created = Profile.objects.get_or_create(user=user)
    user.profile = profile  # re-cache: user.profile must match this instance
    return profile
