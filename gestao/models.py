from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class DonoQuerySet(models.QuerySet):
    """Ponto único de isolamento: todo acesso a dados passa por `do_usuario()`."""

    def do_usuario(self, usuario):
        return self.filter(usuario=usuario)


def _fk_usuario(related_name):
    # editable=False: o dono nunca aparece em formulários nem vem do POST.
    return models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name=related_name,
        editable=False,
    )


class Cliente(models.Model):
    usuario = _fk_usuario("clientes")
    nome = models.CharField("Nome", max_length=150)
    email = models.EmailField("E-mail", blank=True)
    telefone = models.CharField("Telefone", max_length=30, blank=True)
    endereco = models.CharField("Endereço", max_length=255, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    cpf = models.CharField(
        max_length=14, 
        blank=True, 
        null=True, 
        verbose_name="CPF"
    )

    objects = DonoQuerySet.as_manager()

    class Meta:
        ordering = ["nome"]
        verbose_name = "cliente"
        verbose_name_plural = "clientes"

    def __str__(self):
        return self.nome


class Prospeccao(models.Model):
    class Status(models.TextChoices):
        NOVA = "nova", "Nova"
        EM_ANDAMENTO = "andamento", "Em andamento"
        PROPOSTA = "proposta", "Proposta enviada"
        GANHA = "ganha", "Ganha"
        PERDIDA = "perdida", "Perdida"

    usuario = _fk_usuario("prospeccoes")
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name="prospeccoes",
        verbose_name="Cliente",
    )
    descricao = models.TextField("Descrição")
    status = models.CharField(
        "Status", max_length=12, choices=Status.choices, default=Status.NOVA
    )
    data_contato = models.DateField("Data do contato", default=timezone.localdate)
    data_novo_contato = models.DateField("Data do novo contato", null=True, blank=True)
    telefone = models.CharField("Telefone", max_length=30, blank=True)
    data_venda = models.DateTimeField(default=timezone.now, verbose_name="Data da Venda")

    objects = DonoQuerySet.as_manager()

    class Meta:
        ordering = ["-data_contato", "-id"]
        verbose_name = "prospecção"
        verbose_name_plural = "prospecções"

    def __str__(self):
        return f"{self.cliente} - {self.get_status_display()}"


class Produto(models.Model):
    """Item do estoque."""

    usuario = _fk_usuario("produtos")
    nome = models.CharField("Nome", max_length=150)
    quantidade = models.PositiveIntegerField("Quantidade em estoque", default=0)
    preco_compra = models.DecimalField(
        "Preço de compra (custo)",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    preco_venda = models.DecimalField(
        "Preço de venda sugerido",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    objects = DonoQuerySet.as_manager()

    class Meta:
        ordering = ["nome"]
        verbose_name = "item de estoque"
        verbose_name_plural = "itens de estoque"

    def __str__(self):
        return self.nome

    @property
    def margem_unitaria(self):
        return self.preco_venda - self.preco_compra


class Venda(models.Model):
    """
    Venda registrada. Guarda o custo unitário NO MOMENTO da venda, para que o
    lucro histórico não mude se o preço de compra do item for alterado depois.
    """

    usuario = _fk_usuario("vendas")
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name="vendas",
        verbose_name="Cliente",
    )
    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        related_name="vendas",
        verbose_name="Item",
    )
    quantidade = models.PositiveIntegerField(
        "Quantidade", validators=[MinValueValidator(1)]
    )
    preco_venda_praticado = models.DecimalField(
        "Preço de venda praticado", max_digits=12, decimal_places=2
    )
    preco_compra_unitario = models.DecimalField(
        "Custo unitário na data da venda", max_digits=12, decimal_places=2
    )
    total = models.DecimalField("Total da venda", max_digits=14, decimal_places=2)
    lucro = models.DecimalField("Lucro líquido", max_digits=14, decimal_places=2)
    data_venda = models.DateTimeField(
        "Data da venda", default=timezone.now, db_index=True
    )

    objects = DonoQuerySet.as_manager()

    class Meta:
        ordering = ["-data_venda", "-id"]
        verbose_name = "venda"
        verbose_name_plural = "vendas"

    def __str__(self):
        return f"Venda #{self.pk} - {self.produto}"

    def calcular_valores(self):
        """lucro = (preço de venda praticado - preço de compra) * quantidade"""
        self.total = self.preco_venda_praticado * self.quantidade
        self.lucro = (
            self.preco_venda_praticado - self.preco_compra_unitario
        ) * self.quantidade

    def save(self, *args, **kwargs):
        self.calcular_valores()
        super().save(*args, **kwargs)
