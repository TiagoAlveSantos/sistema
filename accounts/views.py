from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import RegistroForm
from .models import UserProfile
from .permissions import superuser_required

User = get_user_model()


def registro(request):
    """Cadastro público. O usuário nasce PENDENTE (ver accounts/signals.py)."""
    if request.user.is_authenticated:
        return redirect("gestao:dashboard")
    if request.method == "POST":
        form = RegistroForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("accounts:registro_concluido")
    else:
        form = RegistroForm()
    return render(request, "accounts/registro.html", {"form": form})


def registro_concluido(request):
    return render(request, "accounts/registro_concluido.html")


# --------------------------------------------------------------------------
# Painel do administrador (somente superusuário): aprovar / reprovar usuários.
# Nenhuma consulta aqui toca clientes, prospecções, estoque ou vendas.
# --------------------------------------------------------------------------
def _garantir_perfis():
    """Rede de segurança: cria perfil (pendente) para usuários sem perfil."""
    sem_perfil = User.objects.filter(is_superuser=False, profile__isnull=True)
    UserProfile.objects.bulk_create([UserProfile(user=u) for u in sem_perfil])


@superuser_required
def painel_usuarios(request):
    _garantir_perfis()

    status_atual = request.GET.get("status", UserProfile.Status.PENDING.value)
    if status_atual not in UserProfile.Status.values:
        status_atual = UserProfile.Status.PENDING.value

    contagens = dict(
        UserProfile.objects.filter(user__is_superuser=False)
        .values_list("status")
        .annotate(total=Count("id"))
    )
    abas = [(s.value, s.label, contagens.get(s.value, 0)) for s in UserProfile.Status]

    usuarios = (
        User.objects.filter(is_superuser=False, profile__status=status_atual)
        .select_related("profile")
        .order_by("-date_joined")
    )
    return render(
        request,
        "accounts/painel_usuarios.html",
        {"usuarios": usuarios, "abas": abas, "status_atual": status_atual},
    )


def _definir_status(request, pk, novo_status, mensagem):
    # is_superuser=False: o painel nunca altera administradores.
    usuario = get_object_or_404(User, pk=pk, is_superuser=False)
    perfil, _ = UserProfile.objects.get_or_create(user=usuario)
    perfil.status = novo_status
    perfil.avaliado_em = timezone.now()
    perfil.avaliado_por = request.user
    perfil.save()
    messages.success(request, mensagem.format(usuario=usuario.get_username()))

    destino = reverse("accounts:painel")
    voltar_para = request.POST.get("status_atual")
    if voltar_para in UserProfile.Status.values:
        destino += "?" + urlencode({"status": voltar_para})
    return redirect(destino)


@superuser_required
@require_POST
def aprovar_usuario(request, pk):
    return _definir_status(
        request, pk, UserProfile.Status.APPROVED, "Usuário {usuario} aprovado."
    )


@superuser_required
@require_POST
def reprovar_usuario(request, pk):
    return _definir_status(
        request, pk, UserProfile.Status.REJECTED, "Usuário {usuario} reprovado."
    )
