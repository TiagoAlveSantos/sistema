from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("gestao", "0006_copiar_vendas_para_itens"),
    ]

    operations = [
        migrations.RemoveField(model_name="venda", name="produto"),
        migrations.RemoveField(model_name="venda", name="quantidade"),
        migrations.RemoveField(model_name="venda", name="preco_venda_praticado"),
        migrations.RemoveField(model_name="venda", name="preco_compra_unitario"),
    ]
