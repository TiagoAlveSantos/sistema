from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F

from .models import Produto, Venda


class EstoqueInsuficiente(Exception):
    """A quantidade pedida é maior que o estoque disponível."""


@transaction.atomic
def registrar_venda(*, usuario, cliente, produto, quantidade, preco_venda_praticado):
    """
    Registra a venda de forma atômica:
      1. confere que cliente e item pertencem ao usuário;
      2. debita o estoque com um UPDATE condicional (seguro contra corrida);
      3. grava a venda com o lucro calculado.
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
    )
