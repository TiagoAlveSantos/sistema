from django.db import migrations


def copiar(apps, schema_editor):
    """Cada venda antiga vira uma venda com 1 item (nada se perde)."""
    Venda = apps.get_model("gestao", "Venda")
    ItemVenda = apps.get_model("gestao", "ItemVenda")
    ItemVenda.objects.bulk_create(
        [
            ItemVenda(
                venda_id=v.pk,
                produto_id=v.produto_id,
                quantidade=v.quantidade,
                preco_venda_praticado=v.preco_venda_praticado,
                preco_compra_unitario=v.preco_compra_unitario,
                total=v.total,
                lucro=v.lucro,
            )
            for v in Venda.objects.all().iterator()
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0005_itemvenda"),
    ]

    operations = [
        migrations.RunPython(copiar, migrations.RunPython.noop),
    ]
