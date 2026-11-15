from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import ItemVenda, Produto, Venda


class EstoqueInsuficiente(Exception):
    """A quantidade pedida é maior que o estoque disponível."""

    def __init__(self, produto="", disponivel=None):
        self.produto = produto
        self.disponivel = disponivel
        if produto:
            msg = f"Estoque insuficiente de “{produto}”"
            if disponivel is not None:
                msg += f" (disponível: {disponivel})"
            msg += "."
        else:
            msg = "Estoque insuficiente."
        super().__init__(msg)


class VendaInvalida(Exception):
    """Dados da venda inconsistentes (ex.: mesmo item repetido)."""


# --------------------------------------------------------------------------
# Auxiliares de estoque (sempre dentro de transaction.atomic)
# --------------------------------------------------------------------------
def _debitar(usuario, produto_id, quantidade, nome):
    """UPDATE condicional: só debita se houver estoque (seguro contra corrida)."""
    debitados = Produto.objects.filter(
        pk=produto_id, usuario=usuario, quantidade__gte=quantidade
    ).update(quantidade=F("quantidade") - quantidade)
    if debitados != 1:
        atual = (
            Produto.objects.filter(pk=produto_id, usuario=usuario)
            .values_list("quantidade", flat=True)
            .first()
        )
        raise EstoqueInsuficiente(nome, atual or 0)


def _devolver(usuario, produto_id, quantidade):
    Produto.objects.filter(pk=produto_id, usuario=usuario).update(
        quantidade=F("quantidade") + quantidade
    )


def _criar_item(usuario, venda, produto, quantidade, preco):
    """Debita o estoque e grava o item com o custo unitário atual do produto."""
    if quantidade < 1:
        raise VendaInvalida("A quantidade deve ser de pelo menos 1.")
    _debitar(usuario, produto.pk, quantidade, produto.nome)
    produto.refresh_from_db()  # custo atual, lido dentro da transação
    return ItemVenda.objects.create(
        venda=venda,
        produto=produto,
        quantidade=quantidade,
        preco_venda_praticado=preco,
        preco_compra_unitario=produto.preco_compra,
    )


# --------------------------------------------------------------------------
# Registrar
# --------------------------------------------------------------------------
@transaction.atomic
def registrar_venda(*, usuario, cliente, itens, data_venda=None):
    """
    Registra uma venda com vários itens, de forma atômica.

    `itens` é uma lista de dicts: {"produto": Produto, "quantidade": int, "preco": Decimal}.
    Qualquer falha (estoque, dono, item repetido) desfaz tudo (rollback).
    """
    if cliente.usuario_id != usuario.pk:
        raise PermissionDenied("Registro não pertence ao usuário.")
    if not itens:
        raise VendaInvalida("Adicione pelo menos um item à venda.")

    vistos = set()
    for it in itens:
        produto = it["produto"]
        if produto.usuario_id != usuario.pk:
            raise PermissionDenied("Registro não pertence ao usuário.")
        if produto.pk in vistos:
            raise VendaInvalida(
                f"O item “{produto.nome}” aparece mais de uma vez. Some as quantidades numa só linha."
            )
        vistos.add(produto.pk)

    venda = Venda.objects.create(
        usuario=usuario,
        cliente=cliente,
        data_venda=data_venda if data_venda else timezone.now(),
        total=0,
        lucro=0,
    )
    # Ordem fixa por produto evita impasses (deadlock) entre vendas simultâneas.
    for it in sorted(itens, key=lambda i: i["produto"].pk):
        _criar_item(usuario, venda, it["produto"], it["quantidade"], it["preco"])
    venda.recalcular_totais()
    return venda


# --------------------------------------------------------------------------
# Reverter (venda inteira ou um item)
# --------------------------------------------------------------------------
@transaction.atomic
def estornar_venda(*, usuario, venda):
    """Devolve ao estoque todos os itens da venda e apaga a venda."""
    try:
        venda = Venda.objects.select_for_update().get(pk=venda.pk, usuario=usuario)
    except Venda.DoesNotExist:
        raise PermissionDenied("Registro não pertence ao usuário.")

    for item in venda.itens.all():
        _devolver(usuario, item.produto_id, item.quantidade)
    venda.delete()  # os itens saem junto (CASCADE)


@transaction.atomic
def estornar_item(*, usuario, item_id):
    """
    Reverte um item: devolve a quantidade ao estoque e remove o item.
    Se era o único item, reverte a venda inteira.
    Retorna True quando a venda inteira foi revertida.
    """
    venda_id = (
        ItemVenda.objects.do_usuario(usuario)
        .filter(pk=item_id)
        .values_list("venda_id", flat=True)
        .first()
    )
    if venda_id is None:
        raise PermissionDenied("Registro não pertence ao usuário.")

    venda = Venda.objects.select_for_update().get(pk=venda_id, usuario=usuario)
    item = venda.itens.filter(pk=item_id).first()  # relê já com a venda travada
    if item is None:
        raise PermissionDenied("Registro não pertence ao usuário.")

    if venda.itens.count() <= 1:
        estornar_venda(usuario=usuario, venda=venda)
        return True

    _devolver(usuario, item.produto_id, item.quantidade)
    item.delete()
    venda.recalcular_totais()
    return False


# --------------------------------------------------------------------------
# Editar
# --------------------------------------------------------------------------
@transaction.atomic
def atualizar_venda(*, usuario, venda_id, cliente, data_venda, itens):
    """
    Edita uma venda mantendo o estoque consistente.

    `itens`: lista de dicts. Com "item_id" = edita um item existente (só
    quantidade e preço; o produto e o custo unitário NUNCA mudam). Sem
    "item_id" = adiciona um item novo ({"produto", "quantidade", "preco"}).
    Itens não citados ficam como estão (para remover, use estornar_item).
    A data original é mantida se não foi alterada (comparando até o minuto).
    """
    try:
        venda = Venda.objects.select_for_update().get(pk=venda_id, usuario=usuario)
    except Venda.DoesNotExist:
        raise PermissionDenied("Registro não pertence ao usuário.")

    if cliente.usuario_id != usuario.pk:
        raise PermissionDenied("Registro não pertence ao usuário.")

    existentes = {i.pk: i for i in venda.itens.select_for_update()}
    produtos_na_venda = {i.produto_id for i in existentes.values()}
    ids_vistos = set()
    novos = []

    for it in itens:
        item_id = it.get("item_id")
        if not item_id:
            novos.append(it)
            continue
        if item_id in ids_vistos:
            raise VendaInvalida("Item repetido no envio.")
        ids_vistos.add(item_id)
        item = existentes.get(item_id)
        if item is None:
            raise PermissionDenied("Registro não pertence ao usuário.")
        if it["quantidade"] < 1:
            raise VendaInvalida("A quantidade deve ser de pelo menos 1.")

        diferenca = it["quantidade"] - item.quantidade
        if diferenca > 0:
            _debitar(usuario, item.produto_id, diferenca, item.produto.nome)
        elif diferenca < 0:
            _devolver(usuario, item.produto_id, -diferenca)
        item.quantidade = it["quantidade"]
        item.preco_venda_praticado = it["preco"]
        item.save()  # recalcula total e lucro com o custo unitário guardado

    for it in novos:
        produto = it["produto"]
        if produto.usuario_id != usuario.pk:
            raise PermissionDenied("Registro não pertence ao usuário.")
        if produto.pk in produtos_na_venda:
            raise VendaInvalida(
                f"O item “{produto.nome}” já está nesta venda. Edite a quantidade da linha existente."
            )
        produtos_na_venda.add(produto.pk)
        _criar_item(usuario, venda, produto, it["quantidade"], it["preco"])

    if data_venda is not None:
        original = timezone.localtime(venda.data_venda).replace(second=0, microsecond=0)
        nova = timezone.localtime(data_venda).replace(second=0, microsecond=0)
        if nova != original:
            venda.data_venda = data_venda

    venda.cliente = cliente
    venda.save()
    venda.recalcular_totais()
    return venda
