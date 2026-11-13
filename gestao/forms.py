import re
from decimal import Decimal

from django import forms

from accounts.forms import BootstrapFormMixin

from .models import Cliente, Produto, Prospeccao

_TELEFONE_RE = re.compile(r"^[0-9+()\-\s.]{6,30}$")


def _validar_telefone(valor):
    valor = (valor or "").strip()
    if valor and not _TELEFONE_RE.match(valor):
        raise forms.ValidationError(
            "Telefone inválido. Use apenas números, espaços e + ( ) - ."
        )
    return valor


class UsuarioModelForm(BootstrapFormMixin, forms.ModelForm):
    """ModelForm que recebe o usuário logado (usado para filtrar os campos de relação)."""

    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)


class ClienteForm(UsuarioModelForm):
    class Meta:
        model = Cliente
        fields = ["nome", "contato", "email", "telefone", "endereco"]

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
    class Meta:
        model = Produto
        fields = ["nome", "quantidade", "preco_compra", "preco_venda"]
        widgets = {
            "quantidade": forms.NumberInput(attrs={"min": "0"}),
            "preco_compra": forms.NumberInput(attrs={"min": "0"}),
            "preco_venda": forms.NumberInput(attrs={"min": "0"}),
        }


class VendaForm(BootstrapFormMixin, forms.Form):
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.none(), label="Cliente", empty_label="Selecione..."
    )
    produto = forms.ModelChoiceField(
        queryset=Produto.objects.none(),
        label="Item do estoque",
        empty_label="Selecione...",
    )
    quantidade = forms.IntegerField(label="Quantidade", min_value=1)
    preco_venda_praticado = forms.DecimalField(
        label="Preço de venda praticado (R$)",
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        help_text="Vem preenchido com o preço sugerido do item; você pode alterá-lo.",
    )

    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)
        self.fields["cliente"].queryset = Cliente.objects.do_usuario(usuario)
        self.fields["produto"].queryset = Produto.objects.do_usuario(usuario).filter(
            quantidade__gt=0
        )
        self.fields["produto"].label_from_instance = (
            lambda p: f"{p.nome} (estoque: {p.quantidade})"
        )

    def clean(self):
        cleaned = super().clean()
        produto = cleaned.get("produto")
        quantidade = cleaned.get("quantidade")
        if produto and quantidade and quantidade > produto.quantidade:
            self.add_error(
                "quantidade",
                f"Estoque insuficiente. Disponível: {produto.quantidade}.",
            )
        return cleaned
