"""
Room views: list, detail (members + activity), create from a book, invite
links (revocable, expiring), member management.
"""
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.annotations.models import AnnotationChange
from apps.library.models import Book
from apps.rooms.forms import RoomForm
from apps.rooms.models import ReadingRoom, RoomMember, RoomRole

app_name = "rooms"


@login_required
def room_list(request):
    mine = (
        ReadingRoom.objects.filter(members__user=request.user, is_active=True)
        .select_related("book", "owner")
        .distinct()
    )
    owned = ReadingRoom.objects.filter(owner=request.user, is_active=True).select_related("book")
    return render(request, "rooms/list.html", {
        "nav": "rooms", "rooms": mine, "owned": owned,
    })


@login_required
def room_detail(request, pk):
    room = get_object_or_404(ReadingRoom.objects.select_related("book", "owner"), pk=pk)
    role = room.member_role(request.user)
    if role is None:
        return render(request, "403.html", status=403)
    members = room.members.select_related("user", "user__profile")
    activity = AnnotationChange.objects.filter(room=room).select_related(
        "actor", "actor__profile"
    ).order_by("-id")[:30]
    invite_url = request.build_absolute_uri(
        f"/rooms/invite/{room.invite_token}/"
    ) if room.invite_valid else ""
    return render(request, "rooms/detail.html", {
        "nav": "rooms", "room": room, "role": role, "members": members,
        "activity": activity, "invite_url": invite_url,
    })


@login_required
@require_POST
def room_create(request, book_id):
    """Create a room for a book ("Start shared reading" on Book Details)."""
    book = get_object_or_404(Book, pk=book_id)
    form = RoomForm(request.POST)
    if form.is_valid():
        room = form.save(commit=False)
        room.book = book
        room.owner = request.user
        room.save()
        RoomMember.objects.create(room=room, user=request.user, role=RoomRole.OWNER)
        room.rotate_invite()
        messages.success(request, f"Room “{room.name}” created.")
        return redirect("rooms:detail", pk=room.pk)
    messages.error(request, "Could not create the room.")
    return redirect("library:detail", pk=book_id)


@login_required
@require_POST
def room_invite_rotate(request, pk):
    room = get_object_or_404(ReadingRoom, pk=pk, owner=request.user)
    room.rotate_invite()
    messages.success(request, "Invite link rotated (old links are now dead).")
    return redirect("rooms:detail", pk=room.pk)


@login_required
@require_POST
def room_invite_revoke(request, pk):
    room = get_object_or_404(ReadingRoom, pk=pk, owner=request.user)
    room.revoke_invite()
    messages.success(request, "Invite link revoked.")
    return redirect("rooms:detail", pk=room.pk)


@login_required
def room_join(request, token):
    room = get_object_or_404(ReadingRoom, invite_token=token, is_active=True)
    if not room.invite_valid:
        messages.error(request, "This invite link has expired.")
        return redirect("rooms:list")
    if room.is_expired:
        messages.error(request, "This room has expired.")
        return redirect("rooms:list")
    member, created = RoomMember.objects.get_or_create(
        room=room, user=request.user, defaults={"role": RoomRole.EDITOR}
    )
    messages.success(request, f"You joined “{room.name}”.")
    return redirect("rooms:detail", pk=room.pk)


@login_required
@require_POST
def room_add_member(request, pk):
    room = get_object_or_404(ReadingRoom, pk=pk)
    if room.member_role(request.user) not in {RoomRole.OWNER} and not request.user.profile.can_moderate_rooms():
        return render(request, "403.html", status=403)
    username = (request.POST.get("username") or "").strip()
    role = request.POST.get("role", RoomRole.EDITOR)
    if role not in RoomRole.values:
        role = RoomRole.EDITOR
    User = get_user_model()
    user = User.objects.filter(username=username).first()
    if user is None:
        messages.error(request, f"No user named “{username}”.")
    else:
        RoomMember.objects.update_or_create(
            room=room, user=user, defaults={"role": role}
        )
        messages.success(request, f"{user.profile.label} added as {role}.")
    return redirect("rooms:detail", pk=room.pk)


@login_required
@require_POST
def room_remove_member(request, pk, user_id):
    room = get_object_or_404(ReadingRoom, pk=pk)
    if room.member_role(request.user) != RoomRole.OWNER and not request.user.profile.can_moderate_rooms():
        return render(request, "403.html", status=403)
    if user_id != room.owner_id:
        RoomMember.objects.filter(room=room, user_id=user_id).delete()
        messages.success(request, "Member removed.")
    return redirect("rooms:detail", pk=room.pk)


urlpatterns = [
    path("", room_list, name="list"),
    path("new/<int:book_id>/", room_create, name="create"),
    path("invite/<str:token>/", room_join, name="join"),
    path("<int:pk>/", room_detail, name="detail"),
    path("<int:pk>/invite/rotate/", room_invite_rotate, name="rotate"),
    path("<int:pk>/invite/revoke/", room_invite_revoke, name="revoke"),
    path("<int:pk>/members/add/", room_add_member, name="add_member"),
    path("<int:pk>/members/<int:user_id>/remove/", room_remove_member, name="remove_member"),
]
