"""Regras de acesso compartilhadas (aprovação, superusuário x usuário comum)."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.shortcuts import redirect

MSG_ADMIN_SEM_ACESSO = (
    "Administradores gerenciam apenas os usuários e não têm acesso aos "
    "dados de clientes, prospecções, estoque ou vendas."
)


def is_user_approved(user):
    """Superusuário sempre pode entrar; os demais precisam estar aprovados."""
    if user.is_superuser:
        return True
    try:
        return user.profile.is_approved
    except ObjectDoesNotExist:
        return False


def superuser_required(view_func):
    """Exige login e superusuário (403 para os demais)."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)


def usuario_comum_required(view_func):
    """Exige login e BLOQUEIA superusuários nos módulos de negócio."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_superuser:
            messages.warning(request, MSG_ADMIN_SEM_ACESSO)
            return redirect("accounts:painel")
        return view_func(request, *args, **kwargs)

    return login_required(_wrapped)


class UsuarioComumMixin(LoginRequiredMixin):
    """Equivalente do @usuario_comum_required para views baseadas em classe."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_superuser:
            messages.warning(request, MSG_ADMIN_SEM_ACESSO)
            return redirect("accounts:painel")
        return super().dispatch(request, *args, **kwargs)
