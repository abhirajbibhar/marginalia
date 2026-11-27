"""Account views: login, logout, profile & preferences."""
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import path, reverse_lazy
from django.views.decorators.http import require_POST

from apps.accounts.forms import ProfileForm
from apps.accounts.models import profile_for

app_name = "accounts"


class LoginView(auth_views.LoginView):
    """Session login; the middleware rate-limits POSTs per IP+username."""

    template_name = "accounts/login.html"
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("accounts:login")


@login_required
def profile(request):
    profile_obj = profile_for(request.user)
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile_obj)
        if form.is_valid():
            form.save()
            user = request.user
            if form.cleaned_data.get("email"):
                user.email = form.cleaned_data["email"]
                user.save(update_fields=["email"])
            messages.success(request, "Profile saved.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=profile_obj, initial={"email": request.user.email})
    return render(request, "accounts/profile.html", {"form": form, "profile": profile_obj})


@login_required
@require_POST
def set_default_layer(request):
    profile_obj = profile_for(request.user)
    layer = request.POST.get("layer", "private")
    if layer in {"private", "room"}:
        profile_obj.default_layer = layer
        profile_obj.save(update_fields=["default_layer"])
    return redirect(request.META.get("HTTP_REFERER", "/"))


urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("profile/", profile, name="profile"),
    path("profile/layer/", set_default_layer, name="set_default_layer"),
]
