import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Cliente",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nome", models.CharField(max_length=150, verbose_name="Nome")),
                (
                    "contato",
                    models.CharField(
                        blank=True, max_length=150, verbose_name="Pessoa de contato"
                    ),
                ),
                (
                    "email",
                    models.EmailField(blank=True, max_length=254, verbose_name="E-mail"),
                ),
                (
                    "telefone",
                    models.CharField(blank=True, max_length=30, verbose_name="Telefone"),
                ),
                (
                    "endereco",
                    models.CharField(blank=True, max_length=255, verbose_name="Endereço"),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "usuario",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="clientes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "cliente",
                "verbose_name_plural": "clientes",
                "ordering": ["nome"],
            },
        ),
        migrations.CreateModel(
            name="Produto",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("nome", models.CharField(max_length=150, verbose_name="Nome")),
                (
                    "quantidade",
                    models.PositiveIntegerField(
                        default=0, verbose_name="Quantidade em estoque"
                    ),
                ),
                (
                    "preco_compra",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Preço de compra (custo)",
                    ),
                ),
                (
                    "preco_venda",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Preço de venda sugerido",
                    ),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "usuario",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="produtos",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "item de estoque",
                "verbose_name_plural": "itens de estoque",
                "ordering": ["nome"],
            },
        ),
        migrations.CreateModel(
            name="Prospeccao",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("descricao", models.TextField(verbose_name="Descrição")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("nova", "Nova"),
                            ("andamento", "Em andamento"),
                            ("proposta", "Proposta enviada"),
                            ("ganha", "Ganha"),
                            ("perdida", "Perdida"),
                        ],
                        default="nova",
                        max_length=12,
                        verbose_name="Status",
                    ),
                ),
                (
                    "data_contato",
                    models.DateField(
                        default=django.utils.timezone.localdate,
                        verbose_name="Data do contato",
                    ),
                ),
                (
                    "data_novo_contato",
                    models.DateField(
                        blank=True, null=True, verbose_name="Data do novo contato"
                    ),
                ),
                (
                    "telefone",
                    models.CharField(blank=True, max_length=30, verbose_name="Telefone"),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                (
                    "cliente",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="prospeccoes",
                        to="gestao.cliente",
                        verbose_name="Cliente",
                    ),
                ),
                (
                    "usuario",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="prospeccoes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "prospecção",
                "verbose_name_plural": "prospecções",
                "ordering": ["-data_contato", "-id"],
            },
        ),
        migrations.CreateModel(
            name="Venda",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "quantidade",
                    models.PositiveIntegerField(
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Quantidade",
                    ),
                ),
                (
                    "preco_venda_praticado",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        verbose_name="Preço de venda praticado",
                    ),
                ),
                (
                    "preco_compra_unitario",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        verbose_name="Custo unitário na data da venda",
                    ),
                ),
                (
                    "total",
                    models.DecimalField(
                        decimal_places=2, max_digits=14, verbose_name="Total da venda"
                    ),
                ),
                (
                    "lucro",
                    models.DecimalField(
                        decimal_places=2, max_digits=14, verbose_name="Lucro líquido"
                    ),
                ),
                (
                    "data_venda",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        verbose_name="Data da venda",
                    ),
                ),
                (
                    "cliente",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vendas",
                        to="gestao.cliente",
                        verbose_name="Cliente",
                    ),
                ),
                (
                    "produto",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vendas",
                        to="gestao.produto",
                        verbose_name="Item",
                    ),
                ),
                (
                    "usuario",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vendas",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "venda",
                "verbose_name_plural": "vendas",
                "ordering": ["-data_venda", "-id"],
            },
        ),
    ]
