from datetime import date, datetime, time, timedelta
from decimal import Decimal


from django.contrib import messages
from django.http import HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.db.models import Count, DecimalField, ProtectedError, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.formats import number_format
from django.views.generic import CreateView, FormView, ListView, UpdateView, DeleteView

from accounts.permissions import UsuarioComumMixin

from .forms import ClienteForm, ProdutoForm, ProspeccaoForm, VendaForm
from .mixins import DonoFormMixin, DonoQuerysetMixin
from .models import Cliente, Produto, Prospeccao, Venda
from .services import EstoqueInsuficiente, registrar_venda, estornar_venda, atualizar_venda


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
        # Pega o queryset base (já filtrado pelo DonoQuerysetMixin) com os selects otimizados
        queryset = super().get_queryset().select_related("cliente", "produto")
        
        # Captura o ID do cliente enviado pelo filtro da URL (?cliente=X)
        cliente_id = self.request.GET.get("cliente", "")
        if cliente_id.isdigit():
            queryset = queryset.filter(cliente_id=int(cliente_id))
            
        return queryset

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Passa apenas os clientes do usuário logado para preencher o menu <select>
        ctx["clientes"] = Cliente.objects.filter(usuario=self.request.user).order_by("nome")
        return ctx


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
                data_venda=form.cleaned_data.get("data_venda"), # Passa a data retroativa se preenchida
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
    
class VendaUpdateView(DonoQuerysetMixin, UpdateView):
    model = Venda
    form_class = VendaForm
    template_name = "gestao/venda_form.html"
    success_url = reverse_lazy("gestao:venda_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        form = ctx["form"]
        # Dados do produto desta venda para o resumo em tempo real do formulário
        ctx["produtos_info"] = {str(form.instance.produto_id): form.info_edicao}
        return ctx

    def form_valid(self, form):
        # NÃO chamamos super().form_valid(): ele salvaria direto, sem ajustar o estoque.
        try:
            atualizar_venda(
                usuario=self.request.user,
                venda_id=self.object.pk,
                cliente=form.cleaned_data["cliente"],
                quantidade=form.cleaned_data["quantidade"],
                preco_venda_praticado=form.cleaned_data["preco_venda_praticado"],
                data_venda=form.cleaned_data.get("data_venda"),
            )
        except EstoqueInsuficiente:
            form.add_error("quantidade", "Estoque insuficiente para esta alteração.")
            return self.form_invalid(form)

        messages.success(self.request, "Venda atualizada e estoque ajustado com sucesso!")
        return HttpResponseRedirect(self.get_success_url())

class VendaDeleteView(DonoQuerysetMixin, DeleteView):
    model = Venda
    template_name = "gestao/venda_confirm_delete.html"
    success_url = reverse_lazy("gestao:venda_list")

    def form_valid(self, form):
        try:
            estornar_venda(usuario=self.request.user, venda=self.object)
            messages.success(self.request, "Venda revertida com sucesso! Os produtos retornaram ao estoque.")
        except Exception as e:
            messages.error(self.request, f"Erro ao reverter venda: {e}")
            return redirect("gestao:venda_list")
        return HttpResponseRedirect(self.success_url)