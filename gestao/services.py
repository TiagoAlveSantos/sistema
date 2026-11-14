from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Produto, Venda


class EstoqueInsuficiente(Exception):
    """A quantidade pedida é maior que o estoque disponível."""


@transaction.atomic
def registrar_venda(*, usuario, cliente, produto, quantidade, preco_venda_praticado, data_venda=None):
    """
    Registra a venda de forma atômica:
      1. confere que cliente e item pertencem ao usuário;
      2. debita o estoque com um UPDATE condicional (seguro contra corrida);
      3. grava a venda com o lucro calculado e data (suporta retroativo).
    Qualquer falha desfaz tudo (rollback).
    """
    if cliente.usuario_id != usuario.pk or produto.usuario_id != usuario.pk:
        raise PermissionDenied("Registro não pertence ao usuário.")

    debitados = Produto.objects.filter(
        pk=produto.pk, usuario=usuario, quantidade__gte=quantidade
    ).update(quantidade=F("quantidade") - quantidade)
    if debitados != 1:
        raise EstoqueInsuficiente()

    produto.refresh_from_db()  # custo atual, lido dentro da transação
    return Venda.objects.create(
        usuario=usuario,
        cliente=cliente,
        produto=produto,
        quantidade=quantidade,
        preco_venda_praticado=preco_venda_praticado,
        preco_compra_unitario=produto.preco_compra,
        data_venda=data_venda if data_venda else timezone.now(),
    )


@transaction.atomic
def estornar_venda(*, usuario, venda):
    """
    Estorna uma venda:
      1. verifica se pertence ao usuário;
      2. devolve a quantidade ao estoque do produto;
      3. exclui o registro da venda.
    """
    if venda.usuario_id != usuario.pk:
        raise PermissionDenied("Registro não pertence ao usuário.")

    Produto.objects.filter(pk=venda.produto_id, usuario=usuario).update(
        quantidade=F("quantidade") + venda.quantidade
    )
    venda.delete()


@transaction.atomic
def atualizar_venda(*, usuario, venda_id, cliente, quantidade, preco_venda_praticado, data_venda=None):
    """
    Edita uma venda mantendo o estoque consistente:
      - quantidade maior  -> debita a diferença do estoque (se houver);
      - quantidade menor  -> devolve a diferença ao estoque;
      - o produto e o custo unitário originais NUNCA mudam;
      - a data original é mantida se não foi alterada (comparando até o minuto).
    """
    try:
        # Lê a venda do banco (valores ORIGINAIS) e trava a linha durante a edição.
        venda = Venda.objects.select_for_update().get(pk=venda_id, usuario=usuario)
    except Venda.DoesNotExist:
        raise PermissionDenied("Registro não pertence ao usuário.")

    if cliente.usuario_id != usuario.pk:
        raise PermissionDenied("Registro não pertence ao usuário.")

    diferenca = quantidade - venda.quantidade
    if diferenca > 0:
        debitados = Produto.objects.filter(
            pk=venda.produto_id, usuario=usuario, quantidade__gte=diferenca
        ).update(quantidade=F("quantidade") - diferenca)
        if debitados != 1:
            raise EstoqueInsuficiente()
    elif diferenca < 0:
        Produto.objects.filter(pk=venda.produto_id, usuario=usuario).update(
            quantidade=F("quantidade") + (-diferenca)
        )

    if data_venda is not None:
        original = timezone.localtime(venda.data_venda).replace(second=0, microsecond=0)
        nova = timezone.localtime(data_venda).replace(second=0, microsecond=0)
        if nova != original:
            venda.data_venda = data_venda

    venda.cliente = cliente
    venda.quantidade = quantidade
    venda.preco_venda_praticado = preco_venda_praticado
    venda.save()  # recalcula total e lucro com o custo unitário guardado na venda
    return venda