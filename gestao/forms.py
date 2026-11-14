import re
from decimal import Decimal

from django import forms

from django.utils import timezone

from accounts.forms import BootstrapFormMixin

from .models import Cliente, Produto, Prospeccao, Venda


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
        fields = ["nome", "cpf", "email", "telefone", "endereco"]

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


class VendaForm(UsuarioModelForm):
    class Meta:
        model = Venda
        fields = ["cliente", "produto", "quantidade", "preco_venda_praticado", "data_venda"]
        widgets = {
            "data_venda": forms.TextInput(
                attrs={"class": "form-control"}
            ),
        }
        labels = {
            "preco_venda_praticado": "Preço de venda praticado (R$)",
            "data_venda": "Data e Hora da Venda",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.fields["cliente"].queryset = Cliente.objects.do_usuario(self.usuario)
        self.fields["cliente"].empty_label = "Selecione..."

        self.fields["produto"].empty_label = "Selecione..."
        self.fields["produto"].label_from_instance = (
            lambda p: f"{p.nome} (estoque: {p.quantidade})"
        )

        # Se for EDIÇÃO
        if self.instance.pk:
            # Trava o campo de produto para não ser alterado
            self.fields["produto"].disabled = True
            self.fields["produto"].queryset = Produto.objects.do_usuario(self.usuario)
            
            # Formata a data existente para o calendário Flatpickr conseguir exibir
            if self.instance.data_venda:
                self.fields["data_venda"].initial = timezone.localtime(self.instance.data_venda).strftime("%Y-%m-%d %H:%M")
        else:
            # Se for NOVA VENDA
            self.fields["produto"].queryset = Produto.objects.do_usuario(self.usuario).filter(
                quantidade__gt=0
            )
            agora_str = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")
            if "data_venda" in self.fields:
                self.fields["data_venda"].initial = agora_str

        # Trava para não aceitar datas futuras no atributo max do HTML
        if "data_venda" in self.fields:
            agora_str_max = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")
            self.fields["data_venda"].widget.attrs["max"] = agora_str_max

    def clean(self):
        cleaned = super().clean()
        produto = cleaned.get("produto")
        quantidade = cleaned.get("quantidade")
        data_venda = cleaned.get("data_venda")

        # Validação de estoque apenas para NOVAS vendas
        if not self.instance.pk and produto and quantidade and quantidade > produto.quantidade:
            self.add_error(
                "quantidade",
                f"Estoque insuficiente. Disponível: {produto.quantidade}.",
            )

        if data_venda and data_venda > timezone.now():
            self.add_error(
                "data_venda",
                "A data da venda não pode ser no futuro.",
            )

        return cleaned