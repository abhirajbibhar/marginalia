"""
Reading rooms: shared annotation layers for one book.

Roles:
* owner  — manage room, members, invites; annotate
* editor — annotate and reply
* viewer — read only

Invite links carry a revocable, expiring token (``invite_token`` +
``token_expires_at``); revoking = rotating/clearing the token.
"""
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.library.models import Book


def make_invite_token() -> str:
    return secrets.token_urlsafe(24)


class RoomRole(models.TextChoices):
    OWNER = "owner", "Owner"
    EDITOR = "editor", "Editor"
    VIEWER = "viewer", "Viewer"


class ReadingRoom(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="rooms")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_rooms"
    )
    name = models.CharField(max_length=200)
    invite_token = models.CharField(max_length=64, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)  # room lifetime
    token_expires_at = models.DateTimeField(null=True, blank=True)  # invite link
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["book", "is_active"])]

    # -- invites ------------------------------------------------------------
    def rotate_invite(self, ttl_days: int = 14) -> str:
        self.invite_token = make_invite_token()
        self.token_expires_at = timezone.now() + timezone.timedelta(days=ttl_days)
        self.save(update_fields=["invite_token", "token_expires_at", "updated_at"])
        return self.invite_token

    def revoke_invite(self) -> None:
        self.invite_token = ""
        self.token_expires_at = None
        self.save(update_fields=["invite_token", "token_expires_at", "updated_at"])

    @property
    def invite_valid(self) -> bool:
        if not self.invite_token:
            return False
        return self.token_expires_at is None or self.token_expires_at > timezone.now()

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    def member_role(self, user) -> str | None:
        """Role of a user in this room, or None when not a member."""
        if not user.is_authenticated:
            return None
        if self.owner_id == user.pk:
            return RoomRole.OWNER
        member = self.members.filter(user=user).first()
        return member.role if member else None

    def can_annotate(self, user) -> bool:
        return self.member_role(user) in {RoomRole.OWNER, RoomRole.EDITOR}

    def can_view(self, user) -> bool:
        return self.member_role(user) is not None

    def __str__(self) -> str:
        return f"{self.name} ({self.book})"


class RoomMember(models.Model):
    room = models.ForeignKey(ReadingRoom, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="room_memberships"
    )
    role = models.CharField(max_length=8, choices=RoomRole.choices, default=RoomRole.EDITOR)
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    last_page = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["joined_at"]
        constraints = [
            models.UniqueConstraint(fields=["room", "user"], name="uniq_room_member")
        ]
        indexes = [models.Index(fields=["room", "-last_seen"])]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.room_id}:{self.role}"
