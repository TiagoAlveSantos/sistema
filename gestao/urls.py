from django.urls import path

from . import views

app_name = "gestao"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Clientes
    path("clientes/", views.ClienteListView.as_view(), name="cliente_list"),
    path("clientes/novo/", views.ClienteCreateView.as_view(), name="cliente_create"),
    path(
        "clientes/<int:pk>/editar/",
        views.ClienteUpdateView.as_view(),
        name="cliente_update",
    ),
    # Prospecções
    path("prospeccoes/", views.ProspeccaoListView.as_view(), name="prospeccao_list"),
    path(
        "prospeccoes/nova/",
        views.ProspeccaoCreateView.as_view(),
        name="prospeccao_create",
    ),
    path(
        "prospeccoes/<int:pk>/editar/",
        views.ProspeccaoUpdateView.as_view(),
        name="prospeccao_update",
    ),
    # Estoque
    path("estoque/", views.ProdutoListView.as_view(), name="produto_list"),
    path("estoque/novo/", views.ProdutoCreateView.as_view(), name="produto_create"),
    path(
        "estoque/<int:pk>/editar/",
        views.ProdutoUpdateView.as_view(),
        name="produto_update",
    ),
    # Vendas
    path("vendas/", views.VendaListView.as_view(), name="venda_list"),
    path("vendas/nova/", views.VendaCreateView.as_view(), name="venda_create"),
]
