from datetime import date, datetime, time, timedelta
from decimal import Decimal


from django.contrib import messages
from django.http import HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, ProtectedError, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.formats import number_format
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from accounts.permissions import UsuarioComumMixin

from .forms import (
    ClienteForm,
    ItemVendaFormSet,
    ItemVendaFormSetEdicao,
    ProdutoForm,
    ProspeccaoForm,
    VendaForm,
    itens_da_formset,
)
from .mixins import DonoFormMixin, DonoQuerysetMixin
from .models import Cliente, ItemVenda, Produto, Prospeccao, Venda
from .services import (
    EstoqueInsuficiente,
    VendaInvalida,
    atualizar_venda,
    estornar_item,
    estornar_venda,
    registrar_venda,
)


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


def _periodos_com_venda(usuario):
    """Lista de (ano, mês) com pelo menos uma venda, do mais recente ao mais antigo."""
    datas = (
        Venda.objects.do_usuario(usuario)
        .annotate(m=TruncMonth("data_venda"))
        .values_list("m", flat=True)
        .distinct()
        .order_by("-m")
    )
    return [(d.year, d.month) for d in datas]


def _inteiro_ou_none(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


@login_required
def dashboard(request):
    usuario = request.user
    if usuario.is_superuser:
        return redirect("accounts:painel")

    periodos = _periodos_com_venda(usuario)
    anos = sorted({a for a, _ in periodos}, reverse=True)

    # ---- Interpreta os filtros (valores inválidos viram "todos") ----
    if "ano" not in request.GET:
        # Padrão: mês mais recente com venda (ou o mês atual, se não há vendas)
        hoje = timezone.localdate()
        ano, mes = periodos[0] if periodos else (hoje.year, hoje.month)
    else:
        ano = _inteiro_ou_none(request.GET.get("ano"))
        if ano not in anos:
            ano = None
        mes = _inteiro_ou_none(request.GET.get("mes"))
        if ano is None or (ano, mes) not in periodos:
            mes = None

    # Se o padrão caiu num ano sem venda (conta nova), garante a lista de anos
    if ano is not None and ano not in anos:
        anos = [ano] + anos
    meses = sorted({m for a, m in periodos if a == ano}, reverse=True) if ano else []
    if mes is not None and mes not in meses:
        meses = sorted(meses + [mes], reverse=True)

    # ---- Período para filtrar ----
    vendas = Venda.objects.do_usuario(usuario)
    prospeccoes = Prospeccao.objects.do_usuario(usuario)
    clientes = Cliente.objects.do_usuario(usuario)

    if ano is not None:
        if mes is not None:
            inicio = date(ano, mes, 1)
            fim = _proximo_mes(inicio)
            sufixo, sufixo_clientes = " no mês", " (até o fim do mês)"
        else:
            inicio, fim = date(ano, 1, 1), date(ano + 1, 1, 1)
            sufixo, sufixo_clientes = " no ano", " (até o fim do ano)"
        tz = timezone.get_current_timezone()
        inicio_dt = datetime.combine(inicio, time.min, tzinfo=tz)
        fim_dt = datetime.combine(fim, time.min, tzinfo=tz)
        vendas = vendas.filter(data_venda__gte=inicio_dt, data_venda__lt=fim_dt)
        prospeccoes = prospeccoes.filter(data_contato__gte=inicio, data_contato__lt=fim)
        clientes = clientes.filter(criado_em__lt=fim_dt)
    else:
        sufixo, sufixo_clientes = "", ""

    resumo = vendas.aggregate(
        total_vendas=_soma("total"),
        total_lucro=_soma("lucro"),
        clientes_compradores=Count("cliente", distinct=True),
    )

    # Valor atual do estoque, ao custo de aquisição (não depende do período)
    valor_estoque = Produto.objects.do_usuario(usuario).aggregate(
        total=Coalesce(
            Sum(
                ExpressionWrapper(
                    F("quantidade") * F("preco_compra"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    )["total"]

    return render(
        request,
        "gestao/dashboard.html",
        {
            "anos": anos,
            "ano_selecionado": ano,
            "meses": [date(ano, m, 1) for m in meses] if ano else [],
            "mes_selecionado": mes,
            "sufixo": sufixo,
            "sufixo_clientes": sufixo_clientes,
            "total_vendas": resumo["total_vendas"],
            "total_lucro": resumo["total_lucro"],
            "clientes_compradores": resumo["clientes_compradores"],
            "qtd_prospeccoes": prospeccoes.count(),
            "total_clientes": clientes.count(),
            "valor_estoque": valor_estoque,
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
                | Q(cpf__icontains=self.busca)
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


class ProdutoDeleteView(DonoQuerysetMixin, DeleteView):
    model = Produto
    template_name = "gestao/produto_confirm_delete.html"
    success_url = reverse_lazy("gestao:produto_list")

    def form_valid(self, form):
        nome = self.object.nome
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(
                self.request,
                f"Não é possível excluir “{nome}”: já existem vendas deste item. "
                "Se não quiser mais vendê-lo, edite e deixe a quantidade em 0.",
            )
            return redirect("gestao:produto_list")
        messages.success(self.request, f"Item “{nome}” excluído do estoque.")
        return HttpResponseRedirect(self.success_url)

# ==========================================================================
# Vendas
# ==========================================================================
class VendaListView(DonoQuerysetMixin, ListView):
    model = Venda
    template_name = "gestao/venda_list.html"
    paginate_by = 20

    def get_queryset(self):
        # Queryset base (já filtrado pelo DonoQuerysetMixin) com os itens pré-carregados
        queryset = (
            super()
            .get_queryset()
            .select_related("cliente")
            .prefetch_related("itens__produto")
        )

        # Filtro por cliente (?cliente=X); valor inválido é ignorado
        cliente_id = self.request.GET.get("cliente", "")
        if cliente_id.isdigit():
            queryset = queryset.filter(cliente_id=int(cliente_id))

        return queryset

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Apenas os clientes do usuário logado no <select>
        ctx["clientes"] = Cliente.objects.do_usuario(self.request.user).order_by("nome")
        return ctx


def _produtos_info(usuario):
    """Dados dos itens do usuário (com estoque) para sugerir o preço no formulário."""
    return {
        str(p.pk): {
            "preco_venda": str(p.preco_venda),
            "custo": str(p.preco_compra),
            "estoque": p.quantidade,
        }
        for p in Produto.objects.do_usuario(usuario).filter(quantidade__gt=0)
    }


class _VendaFormularioView(UsuarioComumMixin, View):
    """Base das telas de nova venda e de edição (cabeçalho + itens)."""

    template_name = "gestao/venda_form.html"
    success_url = reverse_lazy("gestao:venda_list")
    venda = None  # None = nova venda

    def _forms(self, request, data=None):
        raise NotImplementedError

    def _render(self, request, form, formset):
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "object": self.venda,
                "produtos_info": _produtos_info(request.user),
                "tem_produtos": bool(Produto.objects.do_usuario(request.user).filter(quantidade__gt=0).exists()
                                      or (self.venda and self.venda.itens.exists())),
                "tem_clientes": form.fields["cliente"].queryset.exists(),
            },
        )

    def get(self, request, *args, **kwargs):
        form, formset = self._forms(request)
        return self._render(request, form, formset)

    def post(self, request, *args, **kwargs):
        form, formset = self._forms(request, request.POST)
        if form.is_valid() and formset.is_valid():
            try:
                resposta = self._salvar(request, form, formset)
            except EstoqueInsuficiente as e:
                form.add_error(None, str(e))
            except VendaInvalida as e:
                form.add_error(None, str(e))
            else:
                return resposta
        return self._render(request, form, formset)


class VendaCreateView(_VendaFormularioView):
    def _forms(self, request, data=None):
        form = VendaForm(data, usuario=request.user)
        formset = ItemVendaFormSet(
            data, prefix="itens", form_kwargs={"usuario": request.user}
        )
        return form, formset

    def _salvar(self, request, form, formset):
        venda = registrar_venda(
            usuario=request.user,
            cliente=form.cleaned_data["cliente"],
            itens=itens_da_formset(formset),
            data_venda=form.cleaned_data.get("data_venda"),
        )
        lucro = number_format(venda.lucro, 2, use_l10n=True, force_grouping=True)
        messages.success(
            request,
            f"Venda registrada com {venda.itens.count()} item(ns). "
            f"Estoque atualizado. Lucro líquido: R$ {lucro}.",
        )
        return HttpResponseRedirect(self.success_url)


class VendaUpdateView(_VendaFormularioView):
    def dispatch(self, request, *args, **kwargs):
        # Só carrega a venda se o usuário for o dono (senão 404)
        if request.user.is_authenticated and not request.user.is_superuser:
            self.venda = get_object_or_404(
                Venda.objects.do_usuario(request.user), pk=kwargs["pk"]
            )
        return super().dispatch(request, *args, **kwargs)

    def _initial_itens(self):
        """Uma linha por item já gravado (produto e custo ficam fixos)."""
        linhas = []
        for item in self.venda.itens.select_related("produto"):
            linhas.append(
                {
                    "item_id": item.pk,
                    "quantidade": item.quantidade,
                    "preco_venda_praticado": item.preco_venda_praticado,
                    "nome_produto": item.produto.nome,
                    "custo": str(item.preco_compra_unitario),
                    # máximo = o que sobrou no estoque + o que o item já ocupa
                    "max_qtd": item.produto.quantidade + item.quantidade,
                }
            )
        return linhas

    def _forms(self, request, data=None):
        form = VendaForm(data, instance=self.venda, usuario=request.user)
        formset = ItemVendaFormSetEdicao(
            data,
            initial=self._initial_itens(),
            prefix="itens",
            form_kwargs={"usuario": request.user},
        )
        return form, formset

    def _salvar(self, request, form, formset):
        atualizar_venda(
            usuario=request.user,
            venda_id=self.venda.pk,
            cliente=form.cleaned_data["cliente"],
            data_venda=form.cleaned_data.get("data_venda"),
            itens=itens_da_formset(formset),
        )
        messages.success(request, "Venda atualizada e estoque ajustado com sucesso!")
        return HttpResponseRedirect(self.success_url)


class VendaDeleteView(DonoQuerysetMixin, DeleteView):
    """Reverte a venda INTEIRA (todos os itens voltam ao estoque)."""

    model = Venda
    template_name = "gestao/venda_confirm_delete.html"
    success_url = reverse_lazy("gestao:venda_list")

    def get_queryset(self):
        return super().get_queryset().prefetch_related("itens__produto")

    def form_valid(self, form):
        try:
            estornar_venda(usuario=self.request.user, venda=self.object)
            messages.success(
                self.request,
                "Venda revertida com sucesso! Os produtos retornaram ao estoque.",
            )
        except Exception as e:
            messages.error(self.request, f"Erro ao reverter venda: {e}")
            return redirect("gestao:venda_list")
        return HttpResponseRedirect(self.success_url)


class ItemVendaDeleteView(DonoQuerysetMixin, DeleteView):
    """Reverte UM item da venda (se for o único, reverte a venda inteira)."""

    model = ItemVenda
    template_name = "gestao/item_venda_confirm_delete.html"
    success_url = reverse_lazy("gestao:venda_list")

    def get_queryset(self):
        return super().get_queryset().select_related("venda__cliente", "produto")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["unico_item"] = self.object.venda.itens.count() <= 1
        return ctx

    def form_valid(self, form):
        try:
            venda_inteira = estornar_item(
                usuario=self.request.user, item_id=self.object.pk
            )
        except Exception as e:
            messages.error(self.request, f"Erro ao reverter o item: {e}")
            return redirect("gestao:venda_list")
        if venda_inteira:
            messages.success(
                self.request,
                "Era o único item: a venda foi revertida por completo e o estoque devolvido.",
            )
        else:
            messages.success(
                self.request, "Item revertido e devolvido ao estoque. Totais da venda atualizados."
            )
        return HttpResponseRedirect(self.success_url)
