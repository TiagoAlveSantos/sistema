from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import PasswordChangeView
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import captcha
from .forms import RegistroForm, SenhaTemporariaForm, TrocaSenhaForm
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
            if captcha.captcha_ativo() and not captcha.verificar(
                request.POST.get("cf-turnstile-response")
            ):
                form.add_error(
                    None, "Não foi possível confirmar que você não é um robô. Tente de novo."
                )
            else:
                form.save()
                return redirect("accounts:registro_concluido")
    else:
        form = RegistroForm()
    return render(
        request,
        "accounts/registro.html",
        {
            "form": form,
            "turnstile_site_key": settings.TURNSTILE_SITE_KEY if captcha.captcha_ativo() else "",
        },
    )


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


def _alterar_exigencia_troca(request, pk, exigir, mensagem):
    # is_superuser=False: o painel nunca altera administradores.
    usuario = get_object_or_404(User, pk=pk, is_superuser=False)
    perfil, _ = UserProfile.objects.get_or_create(user=usuario)
    perfil.must_change_password = exigir
    perfil.save(update_fields=["must_change_password"])
    messages.success(request, mensagem.format(usuario=usuario.get_username()))

    destino = reverse("accounts:painel")
    voltar_para = request.POST.get("status_atual")
    if voltar_para in UserProfile.Status.values:
        destino += "?" + urlencode({"status": voltar_para})
    return redirect(destino)


@superuser_required
@require_POST
def exigir_troca_senha(request, pk):
    return _alterar_exigencia_troca(
        request,
        pk,
        True,
        "{usuario} precisará trocar a senha no próximo acesso.",
    )


@superuser_required
@require_POST
def cancelar_troca_senha(request, pk):
    return _alterar_exigencia_troca(
        request, pk, False, "Exigência de troca de senha de {usuario} cancelada."
    )


@superuser_required
def definir_senha_temporaria(request, pk):
    """
    O administrador digita uma senha temporária para o usuário. A troca passa a
    ser obrigatória no próximo acesso e as sessões abertas do usuário caem.
    """
    # is_superuser=False: o painel nunca altera administradores.
    usuario = get_object_or_404(User, pk=pk, is_superuser=False)
    if request.method == "POST":
        form = SenhaTemporariaForm(usuario, request.POST)
        if form.is_valid():
            form.save()  # grava o hash; sessões antigas do usuário deixam de valer
            perfil, _ = UserProfile.objects.get_or_create(user=usuario)
            perfil.must_change_password = True
            perfil.save(update_fields=["must_change_password"])
            messages.success(
                request,
                f"Senha temporária definida para {usuario.get_username()}. "
                "Ele precisará trocá-la no próximo acesso.",
            )
            return redirect("accounts:painel")
    else:
        form = SenhaTemporariaForm(usuario)
    return render(
        request,
        "accounts/senha_temporaria.html",
        {"form": form, "usuario_alvo": usuario},
    )


# --------------------------------------------------------------------------
# Troca de senha (qualquer usuário logado; obrigatória se o admin exigiu)
# --------------------------------------------------------------------------
class TrocarSenhaView(PasswordChangeView):
    template_name = "accounts/trocar_senha.html"
    form_class = TrocaSenhaForm
    success_url = reverse_lazy("gestao:dashboard")

    def get_success_url(self):
        if self.request.user.is_superuser:
            return reverse("accounts:painel")
        return super().get_success_url()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        perfil = getattr(self.request.user, "profile", None)
        ctx["obrigatoria"] = bool(perfil and perfil.must_change_password)
        return ctx

    def form_valid(self, form):
        resposta = super().form_valid(form)  # salva e mantém o usuário logado
        UserProfile.objects.filter(user=self.request.user).update(
            must_change_password=False
        )
        messages.success(self.request, "Senha alterada com sucesso.")
        return resposta
