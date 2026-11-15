import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0004_remove_prospeccao_data_venda"),
    ]

    operations = [
        migrations.CreateModel(
            name="ItemVenda",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantidade", models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1)], verbose_name="Quantidade")),
                ("preco_venda_praticado", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="Preço de venda praticado")),
                ("preco_compra_unitario", models.DecimalField(decimal_places=2, max_digits=12, verbose_name="Custo unitário na data da venda")),
                ("total", models.DecimalField(decimal_places=2, max_digits=14, verbose_name="Total do item")),
                ("lucro", models.DecimalField(decimal_places=2, max_digits=14, verbose_name="Lucro líquido do item")),
                ("produto", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="itens_venda", to="gestao.produto", verbose_name="Item")),
                ("venda", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="itens", to="gestao.venda")),
            ],
            options={
                "verbose_name": "item da venda",
                "verbose_name_plural": "itens da venda",
                "ordering": ["id"],
            },
        ),
    ]
