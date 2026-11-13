from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.formats import number_format
from django.views.generic import CreateView, FormView, ListView, UpdateView

from accounts.permissions import UsuarioComumMixin

from .forms import ClienteForm, ProdutoForm, ProspeccaoForm, VendaForm
from .mixins import DonoFormMixin, DonoQuerysetMixin
from .models import Cliente, Produto, Prospeccao, Venda
from .services import EstoqueInsuficiente, registrar_venda


# ==========================================================================
# Dashboard
# ==========================================================================
def _soma(campo):
    return Coalesce(
        Sum(campo),
        Value(Decimal("0.00")),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def _proximo_mes(d):
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def _meses_disponiveis(usuario):
    """Do mês atual até o mês de criação da conta (mais recente primeiro)."""
    atual = timezone.localdate().replace(day=1)
    inicio = timezone.localtime(usuario.date_joined).date().replace(day=1)
    meses = []
    while atual >= inicio:
        meses.append(atual)
        atual = (atual - timedelta(days=1)).replace(day=1)
    return meses or [timezone.localdate().replace(day=1)]


def _interpretar_mes(valor, meses):
    """Aceita 'AAAA-MM' apenas se estiver entre os meses permitidos."""
    try:
        escolhido = datetime.strptime(valor or "", "%Y-%m").date()
    except ValueError:
        return meses[0]
    return escolhido if escolhido in meses else meses[0]


@login_required
def dashboard(request):
    usuario = request.user
    if usuario.is_superuser:
        return redirect("accounts:painel")

    meses = _meses_disponiveis(usuario)
    mes = _interpretar_mes(request.GET.get("mes"), meses)
    proximo = _proximo_mes(mes)

    tz = timezone.get_current_timezone()
    inicio_dt = datetime.combine(mes, time.min, tzinfo=tz)
    fim_dt = datetime.combine(proximo, time.min, tzinfo=tz)

    vendas_mes = Venda.objects.do_usuario(usuario).filter(
        data_venda__gte=inicio_dt, data_venda__lt=fim_dt
    )
    resumo = vendas_mes.aggregate(
        total_vendas=_soma("total"),
        total_lucro=_soma("lucro"),
        clientes_compradores=Count("cliente", distinct=True),
    )
    qtd_prospeccoes = (
        Prospeccao.objects.do_usuario(usuario)
        .filter(data_contato__gte=mes, data_contato__lt=proximo)
        .count()
    )
    total_clientes = (
        Cliente.objects.do_usuario(usuario).filter(criado_em__lt=fim_dt).count()
    )

    return render(
        request,
        "gestao/dashboard.html",
        {
            "meses": meses,
            "mes_selecionado": mes,
            "total_vendas": resumo["total_vendas"],
            "total_lucro": resumo["total_lucro"],
            "clientes_compradores": resumo["clientes_compradores"],
            "qtd_prospeccoes": qtd_prospeccoes,
            "total_clientes": total_clientes,
        },
    )


# ==========================================================================
# Clientes
# ==========================================================================
class ClienteListView(DonoQuerysetMixin, ListView):
    model = Cliente
    template_name = "gestao/cliente_list.html"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        self.busca = self.request.GET.get("q", "").strip()
        if self.busca:
            qs = qs.filter(
                Q(nome__icontains=self.busca)
                | Q(contato__icontains=self.busca)
                | Q(email__icontains=self.busca)
                | Q(telefone__icontains=self.busca)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.busca
        return ctx


class ClienteCreateView(DonoFormMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "gestao/form.html"
    success_url = reverse_lazy("gestao:cliente_list")
    mensagem_sucesso = "Cliente cadastrado com sucesso."
    extra_context = {
        "titulo": "Novo cliente",
        "voltar_url": reverse_lazy("gestao:cliente_list"),
    }


class ClienteUpdateView(DonoFormMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "gestao/form.html"
    success_url = reverse_lazy("gestao:cliente_list")
    mensagem_sucesso = "Cliente atualizado com sucesso."
    extra_context = {
        "titulo": "Editar cliente",
        "voltar_url": reverse_lazy("gestao:cliente_list"),
    }


# ==========================================================================
# Prospecções
# ==========================================================================
class ProspeccaoListView(DonoQuerysetMixin, ListView):
    model = Prospeccao
    template_name = "gestao/prospeccao_list.html"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("cliente")
        self.filtro_status = self.request.GET.get("status", "")
        if self.filtro_status in Prospeccao.Status.values:
            qs = qs.filter(status=self.filtro_status)
        else:
            self.filtro_status = ""
        cliente_id = self.request.GET.get("cliente", "")
        if cliente_id.isdigit():
            qs = qs.filter(cliente_id=int(cliente_id))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = Prospeccao.Status.choices
        ctx["filtro_status"] = self.filtro_status
        ctx["hoje"] = timezone.localdate()
        return ctx


class ProspeccaoCreateView(DonoFormMixin, CreateView):
    model = Prospeccao
    form_class = ProspeccaoForm
    template_name = "gestao/form.html"
    success_url = reverse_lazy("gestao:prospeccao_list")
    mensagem_sucesso = "Prospecção cadastrada com sucesso."
    extra_context = {
        "titulo": "Nova prospecção",
        "voltar_url": reverse_lazy("gestao:prospeccao_list"),
    }

    def get_initial(self):
        initial = super().get_initial()
        cliente_id = self.request.GET.get("cliente", "")
        # Só pré-seleciona se o cliente for do próprio usuário.
        if (
            cliente_id.isdigit()
            and Cliente.objects.do_usuario(self.request.user)
            .filter(pk=int(cliente_id))
            .exists()
        ):
            initial["cliente"] = int(cliente_id)
        return initial


class ProspeccaoUpdateView(DonoFormMixin, UpdateView):
    model = Prospeccao
    form_class = ProspeccaoForm
    template_name = "gestao/form.html"
    success_url = reverse_lazy("gestao:prospeccao_list")
    mensagem_sucesso = "Prospecção atualizada com sucesso."
    extra_context = {
        "titulo": "Editar prospecção",
        "voltar_url": reverse_lazy("gestao:prospeccao_list"),
    }


# ==========================================================================
# Estoque
# ==========================================================================
class ProdutoListView(DonoQuerysetMixin, ListView):
    model = Produto
    template_name = "gestao/produto_list.html"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        self.busca = self.request.GET.get("q", "").strip()
        if self.busca:
            qs = qs.filter(nome__icontains=self.busca)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.busca
        return ctx


class ProdutoCreateView(DonoFormMixin, CreateView):
    model = Produto
    form_class = ProdutoForm
    template_name = "gestao/form.html"
    success_url = reverse_lazy("gestao:produto_list")
    mensagem_sucesso = "Item cadastrado no estoque."
    extra_context = {
        "titulo": "Novo item de estoque",
        "voltar_url": reverse_lazy("gestao:produto_list"),
    }


class ProdutoUpdateView(DonoFormMixin, UpdateView):
    model = Produto
    form_class = ProdutoForm
    template_name = "gestao/form.html"
    success_url = reverse_lazy("gestao:produto_list")
    mensagem_sucesso = "Item atualizado com sucesso."
    extra_context = {
        "titulo": "Editar item de estoque",
        "voltar_url": reverse_lazy("gestao:produto_list"),
    }


# ==========================================================================
# Vendas
# ==========================================================================
class VendaListView(DonoQuerysetMixin, ListView):
    model = Venda
    template_name = "gestao/venda_list.html"
    paginate_by = 20

    def get_queryset(self):
        return super().get_queryset().select_related("cliente", "produto")


class VendaCreateView(UsuarioComumMixin, FormView):
    template_name = "gestao/venda_form.html"
    form_class = VendaForm
    success_url = reverse_lazy("gestao:venda_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Dados dos itens do próprio usuário, para sugerir o preço no formulário.
        ctx["produtos_info"] = {
            str(p.pk): {
                "preco_venda": str(p.preco_venda),
                "custo": str(p.preco_compra),
                "estoque": p.quantidade,
            }
            for p in ctx["form"].fields["produto"].queryset
        }
        return ctx

    def form_valid(self, form):
        try:
            venda = registrar_venda(
                usuario=self.request.user,
                cliente=form.cleaned_data["cliente"],
                produto=form.cleaned_data["produto"],
                quantidade=form.cleaned_data["quantidade"],
                preco_venda_praticado=form.cleaned_data["preco_venda_praticado"],
            )
        except EstoqueInsuficiente:
            form.add_error("quantidade", "Estoque insuficiente para esta venda.")
            return self.form_invalid(form)

        lucro = number_format(venda.lucro, 2, use_l10n=True, force_grouping=True)
        messages.success(
            self.request,
            f"Venda registrada. Estoque atualizado. Lucro líquido: R$ {lucro}.",
        )
        return super().form_valid(form)
