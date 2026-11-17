from django.db import migrations
from django.utils import timezone


def criar(apps, schema_editor):
    """Vendas já existentes ganham 1 pagamento 'Outro' PENDENTE (vencimento = data da venda),
    para a pessoa conferir e ajustar/confirmar cada uma."""
    Venda = apps.get_model("gestao", "Venda")
    Pagamento = apps.get_model("gestao", "Pagamento")
    Pagamento.objects.bulk_create(
        [
            Pagamento(
                venda_id=v.pk,
                metodo="outro",
                valor=v.total,
                data=timezone.localtime(v.data_venda).date(),
                pago=False,
            )
            for v in Venda.objects.filter(total__gt=0).iterator()
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0008_pagamento"),
    ]

    operations = [
        migrations.RunPython(criar, migrations.RunPython.noop),
    ]
