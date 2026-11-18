import re
from decimal import Decimal

from django import forms

from django.utils import timezone

from accounts.forms import BootstrapFormMixin

from django.core.validators import MaxValueValidator
from django.db.models.functions import Lower

from .limites import PRECO_MAX, QTD_MAX
from .models import Cliente, Pagamento, Produto, Prospeccao, Venda


_TELEFONE_RE = re.compile(r"^[0-9+()\-\s.]{6,30}$")


def _validar_telefone(valor):
    valor = (valor or "").strip()
    if valor and not _TELEFONE_RE.match(valor):
        raise forms.ValidationError(
            "Telefone inválido. Use apenas números, espaços e + ( ) - ."
        )
    return valor


def _validar_cpf(valor):
    """Aceita só dígitos ou com pontuação; valida os dígitos verificadores
    e devolve no formato 000.000.000-00 (ou None se vazio)."""
    digitos = re.sub(r"\D", "", valor or "")
    if not digitos:
        return None
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        raise forms.ValidationError("CPF inválido.")
    for i in (9, 10):
        soma = sum(int(digitos[n]) * (i + 1 - n) for n in range(i))
        if (soma * 10) % 11 % 10 != int(digitos[i]):
            raise forms.ValidationError("CPF inválido.")
    return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"


class UsuarioModelForm(BootstrapFormMixin, forms.ModelForm):
    """ModelForm que recebe o usuário logado (usado para filtrar os campos de relação)."""

    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)


class ClienteForm(UsuarioModelForm):
    class Meta:
        model = Cliente
        fields = ["nome", "cpf", "email", "telefone", "endereco"]
        widgets = {
            "cpf": forms.TextInput(
                attrs={"placeholder": "000.000.000-00", "inputmode": "numeric"}
            ),
        }

    def clean_cpf(self):
        cpf = _validar_cpf(self.cleaned_data.get("cpf"))
        if (
            cpf
            and Cliente.objects.do_usuario(self.usuario)
            .filter(cpf=cpf)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError("Você já tem um cliente cadastrado com este CPF.")
        return cpf

    def clean_telefone(self):
        return _validar_telefone(self.cleaned_data.get("telefone"))


class ProspeccaoForm(UsuarioModelForm):
    class Meta:
        model = Prospeccao
        fields = [
            "cliente",
            "descricao",
            "status",
            "data_contato",
            "data_novo_contato",
            "telefone",
        ]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 3}),
            "data_contato": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "data_novo_contato": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Só clientes DO usuário logado: IDs de outros usuários são rejeitados.
        self.fields["cliente"].queryset = Cliente.objects.do_usuario(self.usuario)
        self.fields["cliente"].empty_label = "Selecione o cliente..."

    def clean_telefone(self):
        return _validar_telefone(self.cleaned_data.get("telefone"))

    def clean(self):
        cleaned = super().clean()
        contato = cleaned.get("data_contato")
        novo = cleaned.get("data_novo_contato")
        if contato and novo and novo < contato:
            self.add_error(
                "data_novo_contato",
                "O novo contato não pode ser anterior à data do contato.",
            )
        return cleaned


class ProdutoForm(UsuarioModelForm):
    # Guarda a quantidade vista ao abrir a tela: se uma venda alterar o estoque
    # enquanto a tela está aberta, o salvamento é barrado (evita sobrescrever).
    quantidade_original = forms.IntegerField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Produto
        fields = ["nome", "quantidade", "preco_compra", "preco_venda"]
        widgets = {
            "quantidade": forms.NumberInput(attrs={"min": "0", "max": str(QTD_MAX)}),
            "preco_compra": forms.NumberInput(attrs={"min": "0", "max": str(PRECO_MAX)}),
            "preco_venda": forms.NumberInput(attrs={"min": "0", "max": str(PRECO_MAX)}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["quantidade"].validators.append(
            MaxValueValidator(
                QTD_MAX, message=f"A quantidade máxima por item é {QTD_MAX:,}.".replace(",", ".")
            )
        )
        for nome in ("preco_compra", "preco_venda"):
            self.fields[nome].validators.append(
                MaxValueValidator(PRECO_MAX, message="O valor máximo por unidade é R$ 999.999,99.")
            )
        if self.instance.pk:
            # self.instance foi lido do banco agora: é o estoque ATUAL.
            self._quantidade_db = self.instance.quantidade
            self.fields["quantidade_original"].initial = self._quantidade_db
        else:
            del self.fields["quantidade_original"]

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk:
            original = cleaned.get("quantidade_original")
            if original is not None and original != self._quantidade_db:
                # Atualiza o valor "visto" para o próximo envio e avisa o usuário.
                dados = self.data.copy()
                dados["quantidade_original"] = str(self._quantidade_db)
                self.data = dados
                self.add_error(
                    "quantidade",
                    f"O estoque deste item mudou enquanto você editava (agora são "
                    f"{self._quantidade_db}). Confira a quantidade e salve de novo.",
                )
        return cleaned


class VendaForm(UsuarioModelForm):
    """Cabeçalho da venda: cliente e data. Os itens vão no formset abaixo."""

    class Meta:
        model = Venda
        fields = ["cliente", "data_venda"]
        widgets = {
            "data_venda": forms.TextInput(attrs={"class": "form-control"}),
        }
        labels = {"data_venda": "Data e Hora da Venda"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].queryset = Cliente.objects.do_usuario(self.usuario)
        self.fields["cliente"].empty_label = "Selecione..."

        agora_str = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")
        if self.instance.pk:
            # Edição: mantém a data original no campo (self.initial vence field.initial)
            self.initial["data_venda"] = timezone.localtime(
                self.instance.data_venda
            ).strftime("%Y-%m-%d %H:%M")
        else:
            self.fields["data_venda"].initial = agora_str
        self.fields["data_venda"].widget.attrs["max"] = agora_str

    def clean_data_venda(self):
        data_venda = self.cleaned_data.get("data_venda")
        if data_venda and data_venda > timezone.now():
            raise forms.ValidationError("A data da venda não pode ser no futuro.")
        return data_venda


class ItemVendaForm(BootstrapFormMixin, forms.Form):
    """
    Uma linha da venda. Linhas já existentes (edição) trazem `item_id`: nelas só
    quantidade e preço mudam, e o produto enviado é IGNORADO (o serviço usa o
    produto gravado no item). Linhas novas exigem o produto.
    """

    item_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    produto = forms.ModelChoiceField(
        queryset=Produto.objects.none(),
        required=False,
        empty_label="Selecione o item...",
        label="Item",
    )
    quantidade = forms.IntegerField(
        min_value=1,
        max_value=QTD_MAX,
        label="Qtd.",
        widget=forms.NumberInput(attrs={"min": "1"}),
    )
    preco_venda_praticado = forms.DecimalField(
        min_value=0,
        max_value=PRECO_MAX,
        max_digits=12,
        decimal_places=2,
        label="Preço (R$)",
        widget=forms.NumberInput(attrs={"min": "0", "max": str(PRECO_MAX), "step": "0.01"}),
    )

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        # Só itens DO usuário e com estoque: IDs de outros usuários são rejeitados.
        # Em ordem alfabética (sem diferenciar maiúsculas/minúsculas)
        qs = (
            Produto.objects.do_usuario(usuario)
            .filter(quantidade__gt=0)
            .order_by(Lower("nome"), "pk")
        )
        self.fields["produto"].queryset = qs
        self.fields["produto"].label_from_instance = (
            lambda p: f"{p.nome} (estoque: {p.quantidade})"
        )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("item_id") and not cleaned.get("produto"):
            self.add_error("produto", "Selecione o item.")
        return cleaned


class SemLinhasFantasmaMixin:
    """
    O navegador numera as linhas e nunca renumera: ao remover uma linha, o POST traz um
    "buraco" no índice (TOTAL_FORMS maior que as linhas enviadas). Ao reexibir o formulário
    com erro, esse buraco viraria uma linha em branco. `forms_visiveis` o descarta.
    """

    def forms_visiveis(self):
        if not self.is_bound:
            return list(self.forms)
        return [
            f for f in self.forms
            if any(f.add_prefix(nome) in self.data for nome in f.fields)
        ]


class BaseItemVendaFormSet(SemLinhasFantasmaMixin, forms.BaseFormSet):
    def clean(self):
        if any(self.errors):
            return
        produtos = set()
        total = 0
        for form in self.forms:
            dados = getattr(form, "cleaned_data", None)
            if not dados:  # linha vazia (extra não preenchida)
                continue
            total += 1
            produto = dados.get("produto")
            if produto and not dados.get("item_id"):
                if produto.pk in produtos:
                    raise forms.ValidationError(
                        f"O item “{produto.nome}” aparece mais de uma vez. "
                        "Some as quantidades numa só linha."
                    )
                produtos.add(produto.pk)
        if total == 0:
            raise forms.ValidationError("Adicione pelo menos um item à venda.")


# Nova venda: começa com 1 linha. Edição: só as linhas existentes (o resto é por JS).
ItemVendaFormSet = forms.formset_factory(
    ItemVendaForm, formset=BaseItemVendaFormSet, extra=1
)
ItemVendaFormSetEdicao = forms.formset_factory(
    ItemVendaForm, formset=BaseItemVendaFormSet, extra=0
)


def itens_da_formset(formset):
    """Converte as linhas válidas do formset na lista esperada pelos serviços."""
    itens = []
    for form in formset.forms:
        dados = getattr(form, "cleaned_data", None)
        if not dados:
            continue
        itens.append(
            {
                "item_id": dados.get("item_id"),
                "produto": dados.get("produto"),
                "quantidade": dados["quantidade"],
                "preco": dados["preco_venda_praticado"],
            }
        )
    return itens


# --------------------------------------------------------------------------
# Pagamentos da venda
# --------------------------------------------------------------------------
class PagamentoForm(BootstrapFormMixin, forms.Form):
    """Uma linha de pagamento: meio, valor, data (pagamento ou vencimento) e se já foi pago."""

    # Sem `initial` nos campos: linhas removidas no navegador (índices "furados" no POST)
    # precisam parecer vazias para o formset ignorá-las. Os padrões vêm da view/JS.
    metodo = forms.ChoiceField(choices=Pagamento.Metodo.choices, label="Meio")
    valor = forms.DecimalField(
        min_value=Decimal("0.01"),
        # Sem teto aqui de propósito: o limite do TOTAL é checado pelo serviço, que dá a
        # mensagem clara ("grande demais"); um pagamento fora do total nunca fecha a conta.
        max_digits=20,
        decimal_places=2,
        label="Valor (R$)",
        widget=forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
    )
    data = forms.DateField(
        label="Data",
        # Texto ISO (AAAA-MM-DD) que o Flatpickr mostra como dd/mm/aaaa na tela
        widget=forms.DateInput(attrs={"autocomplete": "off"}, format="%Y-%m-%d"),
    )
    pago = forms.BooleanField(required=False, label="Já pago")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pago"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        cleaned = super().clean()
        data, pago = cleaned.get("data"), cleaned.get("pago")
        if data and pago and data > timezone.localdate():
            self.add_error(
                "data", "Pagamento já recebido não pode ter data futura. Desmarque “Já pago”."
            )
        return cleaned


class BasePagamentoFormSet(SemLinhasFantasmaMixin, forms.BaseFormSet):
    def initial_form_count(self):
        # Ao receber o POST, todas as linhas são tratadas como "novas": o serviço
        # SUBSTITUI os pagamentos. Assim, linhas removidas no navegador somem sem erro.
        if self.is_bound:
            return 0
        return super().initial_form_count()


# Sem linhas extras: as linhas iniciais vêm de `initial` (ou são criadas pelo JS).
PagamentoFormSet = forms.formset_factory(
    PagamentoForm, formset=BasePagamentoFormSet, extra=0
)


def pagamentos_da_formset(formset):
    """Converte as linhas válidas do formset na lista esperada pelos serviços."""
    lista = []
    for form in formset.forms:
        dados = getattr(form, "cleaned_data", None)
        if not dados:
            continue
        lista.append(
            {
                "metodo": dados["metodo"],
                "valor": dados["valor"],
                "data": dados["data"],
                "pago": dados.get("pago", False),
            }
        )
    return lista
