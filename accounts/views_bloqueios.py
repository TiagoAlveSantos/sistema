"""Tela do administrador para ver e desbloquear tentativas de login (django-axes)."""
from axes.helpers import get_cool_off
from axes.models import AccessAttempt
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .permissions import superuser_required


def _linhas():
    limite = settings.AXES_FAILURE_LIMIT
    cool = get_cool_off()  # timedelta (ou None = bloqueio sem prazo)
    agora = timezone.now()
    linhas = []
    for t in AccessAttempt.objects.order_by("-attempt_time"):
        atingiu = t.failures_since_start >= limite
        libera_em = (t.attempt_time + cool) if cool else None
        expirou = bool(libera_em and libera_em <= agora)
        linhas.append(
            {
                "pk": t.pk,
                "username": t.username or "—",
                "ip": t.ip_address or "—",
                "falhas": t.failures_since_start,
                "ultima": t.attempt_time,
                "bloqueado": atingiu and not expirou,
                "libera_em": libera_em if atingiu and not expirou else None,
                "expirado": expirou,
            }
        )
    return linhas, limite


@superuser_required
def bloqueios(request):
    linhas, limite = _linhas()
    return render(
        request,
        "accounts/bloqueios.html",
        {
            "linhas": linhas,
            "limite": limite,
            "total_bloqueados": sum(1 for x in linhas if x["bloqueado"]),
        },
    )


@superuser_required
@require_POST
def desbloquear(request, pk):
    apagados, _ = AccessAttempt.objects.filter(pk=pk).delete()
    if apagados:
        messages.success(request, "Bloqueio removido. O usuário já pode tentar entrar de novo.")
    else:
        messages.info(request, "Esse registro já não existe (talvez o bloqueio tenha expirado).")
    return redirect("accounts:bloqueios")


@superuser_required
@require_POST
def desbloquear_todos(request):
    apagados, _ = AccessAttempt.objects.all().delete()
    messages.success(request, f"{apagados} registro(s) de tentativa removido(s). Todos desbloqueados.")
    return redirect("accounts:bloqueios")
