import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0007_remove_campos_antigos_venda"),
    ]

    operations = [
        migrations.CreateModel(
            name="Pagamento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "metodo",
                    models.CharField(
                        choices=[
                            ("pix", "Pix"),
                            ("dinheiro", "Dinheiro"),
                            ("credito", "Cartão de crédito"),
                            ("debito", "Cartão de débito"),
                            ("transferencia", "Transferência"),
                            ("boleto", "Boleto"),
                            ("outro", "Outro"),
                        ],
                        default="outro",
                        max_length=20,
                        verbose_name="Meio de pagamento",
                    ),
                ),
                ("valor", models.DecimalField(decimal_places=2, max_digits=14, verbose_name="Valor")),
                ("data", models.DateField(verbose_name="Data")),
                ("pago", models.BooleanField(default=False, verbose_name="Pago")),
                (
                    "venda",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pagamentos",
                        to="gestao.venda",
                    ),
                ),
            ],
            options={
                "verbose_name": "pagamento",
                "verbose_name_plural": "pagamentos",
                "ordering": ["data", "id"],
            },
        ),
    ]
