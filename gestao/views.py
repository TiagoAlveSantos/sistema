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
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from accounts.permissions import UsuarioComumMixin

from .forms import (
    ClienteForm,
    ItemVendaFormSet,
    ItemVendaFormSetEdicao,
    PagamentoFormSet,
    ProdutoForm,
    ProspeccaoForm,
    VendaForm,
    itens_da_formset,
    pagamentos_da_formset,
)
from .mixins import DonoFormMixin, DonoQuerysetMixin
from .models import Cliente, ItemVenda, Pagamento, Produto, Prospeccao, Venda
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

    # Pagamentos: recebido (pagos, pela data do pagamento) e a receber (pendentes,
    # pelo vencimento) dentro do período; "atrasado" olha tudo que venceu e não foi pago.
    pagamentos = Pagamento.objects.do_usuario(usuario)
    pagamentos_periodo = pagamentos
    if ano is not None:
        pagamentos_periodo = pagamentos.filter(data__gte=inicio, data__lt=fim)
    recebido = pagamentos_periodo.filter(pago=True).aggregate(t=_soma("valor"))["t"]
    a_receber = pagamentos_periodo.filter(pago=False).aggregate(t=_soma("valor"))["t"]
    atrasado = pagamentos.filter(pago=False, data__lt=timezone.localdate()).aggregate(
        t=_soma("valor")
    )["t"]

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
            "recebido": recebido,
            "a_receber": a_receber,
            "atrasado": atrasado,
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
FILTROS_PAGAMENTO = ("pendente", "atrasado", "quitado", "ajustar")


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
            .prefetch_related("itens__produto", "pagamentos")
        )

        # Filtro por situação do pagamento (?pagamento=...); valor inválido é ignorado
        self.filtro_pagamento = self.request.GET.get("pagamento", "")
        if self.filtro_pagamento in FILTROS_PAGAMENTO:
            zero = Value(Decimal("0.00"))
            dec = DecimalField(max_digits=14, decimal_places=2)
            hoje = timezone.localdate()
            queryset = queryset.annotate(
                soma_paga=Coalesce(
                    Sum("pagamentos__valor", filter=Q(pagamentos__pago=True)),
                    zero, output_field=dec,
                ),
                soma_pendente=Coalesce(
                    Sum("pagamentos__valor", filter=Q(pagamentos__pago=False)),
                    zero, output_field=dec,
                ),
                soma_atrasada=Coalesce(
                    Sum(
                        "pagamentos__valor",
                        filter=Q(pagamentos__pago=False, pagamentos__data__lt=hoje),
                    ),
                    zero, output_field=dec,
                ),
            )
            fecha = Q(total=F("soma_paga") + F("soma_pendente"))
            if self.filtro_pagamento == "pendente":
                queryset = queryset.filter(fecha, soma_pendente__gt=0)
            elif self.filtro_pagamento == "atrasado":
                queryset = queryset.filter(fecha, soma_atrasada__gt=0)
            elif self.filtro_pagamento == "quitado":
                queryset = queryset.filter(fecha, soma_pendente=0)
            else:  # ajustar
                queryset = queryset.exclude(fecha)

        # Filtro por cliente (?cliente=X); valor inválido é ignorado
        cliente_id = self.request.GET.get("cliente", "")
        if cliente_id.isdigit():
            queryset = queryset.filter(cliente_id=int(cliente_id))

        return queryset

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Apenas os clientes do usuário logado no <select>
        ctx["clientes"] = Cliente.objects.do_usuario(self.request.user).order_by("nome")
        ctx["filtro_pagamento"] = getattr(self, "filtro_pagamento", "")
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

    def _render(self, request, form, formset, pformset):
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "pformset": pformset,
                "metodos": Pagamento.Metodo.choices,
                "object": self.venda,
                "produtos_info": _produtos_info(request.user),
                "tem_produtos": bool(Produto.objects.do_usuario(request.user).filter(quantidade__gt=0).exists()
                                      or (self.venda and self.venda.itens.exists())),
                "tem_clientes": form.fields["cliente"].queryset.exists(),
            },
        )

    def get(self, request, *args, **kwargs):
        form, formset, pformset = self._forms(request)
        return self._render(request, form, formset, pformset)

    def post(self, request, *args, **kwargs):
        form, formset, pformset = self._forms(request, request.POST)
        # all() avalia os três (assim todos os erros aparecem de uma vez)
        if all([form.is_valid(), formset.is_valid(), pformset.is_valid()]):
            try:
                resposta = self._salvar(request, form, formset, pformset)
            except EstoqueInsuficiente as e:
                form.add_error(None, str(e))
            except VendaInvalida as e:
                form.add_error(None, str(e))
            else:
                return resposta
        return self._render(request, form, formset, pformset)


class VendaCreateView(_VendaFormularioView):
    def _forms(self, request, data=None):
        form = VendaForm(data, usuario=request.user)
        formset = ItemVendaFormSet(
            data, prefix="itens", form_kwargs={"usuario": request.user}
        )
        # Começa com 1 linha: Pix, já pago, hoje (o JS preenche o valor com o total)
        pformset = PagamentoFormSet(
            data,
            initial=None
            if data is not None
            else [{"metodo": "pix", "data": timezone.localdate(), "pago": True}],
            prefix="pgtos",
        )
        return form, formset, pformset

    def _salvar(self, request, form, formset, pformset):
        venda = registrar_venda(
            usuario=request.user,
            cliente=form.cleaned_data["cliente"],
            itens=itens_da_formset(formset),
            pagamentos=pagamentos_da_formset(pformset),
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
        pformset = PagamentoFormSet(
            data,
            initial=None if data is not None else self._initial_pagamentos(),
            prefix="pgtos",
        )
        return form, formset, pformset

    def _initial_pagamentos(self):
        return [
            {"metodo": p.metodo, "valor": p.valor, "data": p.data, "pago": p.pago}
            for p in self.venda.pagamentos.all()
        ]

    def _salvar(self, request, form, formset, pformset):
        atualizar_venda(
            usuario=request.user,
            venda_id=self.venda.pk,
            cliente=form.cleaned_data["cliente"],
            data_venda=form.cleaned_data.get("data_venda"),
            itens=itens_da_formset(formset),
            pagamentos=pagamentos_da_formset(pformset),
        )
        messages.success(request, "Venda atualizada e estoque ajustado com sucesso!")
        return HttpResponseRedirect(self.success_url)


class VendaDeleteView(DonoQuerysetMixin, DeleteView):
    """Reverte a venda INTEIRA (todos os itens voltam ao estoque)."""

    model = Venda
    template_name = "gestao/venda_confirm_delete.html"
    success_url = reverse_lazy("gestao:venda_list")

    def get_queryset(self):
        return super().get_queryset().prefetch_related("itens__produto", "pagamentos")

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
        venda_id = self.object.venda_id
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
            return HttpResponseRedirect(self.success_url)
        venda = Venda.objects.do_usuario(self.request.user).get(pk=venda_id)
        if venda.pagamentos_resumo()["estado"] == "ajustar":
            messages.warning(
                self.request,
                "Item revertido e devolvido ao estoque. O total da venda mudou: "
                "ajuste os pagamentos abaixo e salve.",
            )
            return redirect("gestao:venda_update", pk=venda_id)
        messages.success(
            self.request, "Item revertido e devolvido ao estoque. Totais da venda atualizados."
        )
        return HttpResponseRedirect(self.success_url)


class _PagamentoAcaoView(UsuarioComumMixin, View):
    """Marca/desmarca UM pagamento como pago (só POST; só o dono da venda)."""

    http_method_names = ["post"]
    pago = True

    def post(self, request, pk):
        pagamento = get_object_or_404(
            Pagamento.objects.do_usuario(request.user), pk=pk
        )
        if self.pago:
            # A data passa a ser a do recebimento (hoje)
            pagamento.pago, pagamento.data = True, timezone.localdate()
            pagamento.save(update_fields=["pago", "data"])
            messages.success(
                request, f"Pagamento de R$ {number_format(pagamento.valor, 2, use_l10n=True, force_grouping=True)} confirmado."
            )
        else:
            pagamento.pago = False
            pagamento.save(update_fields=["pago"])
            messages.info(request, "Pagamento voltou para pendente.")
        destino = request.POST.get("next", "")
        if not url_has_allowed_host_and_scheme(
            destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            destino = reverse_lazy("gestao:venda_list")
        return HttpResponseRedirect(destino)


class PagamentoConfirmarView(_PagamentoAcaoView):
    pago = True


class PagamentoDesfazerView(_PagamentoAcaoView):
    pago = False
