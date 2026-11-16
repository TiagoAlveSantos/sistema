"""Limites numéricos do sistema (evitam estouro dos campos do banco)."""
from decimal import Decimal

# Quantidade máxima por item de estoque / por linha de venda.
QTD_MAX = 1_000_000
# Preço máximo (venda ou custo) por unidade.
PRECO_MAX = Decimal("999999.99")
# Os totais da venda ficam em colunas de 14 dígitos (2 decimais): < 10^12.
# QTD_MAX * PRECO_MAX = 999.999.990.000,00 já cabe; a soma de vários itens é
# conferida em services._fechar_venda().
TOTAL_MAX = Decimal("999999999999.99")
