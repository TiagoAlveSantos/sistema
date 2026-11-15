from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=LoginForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    # Logout exige POST (formulário com CSRF no menu).
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("registro/", views.registro, name="registro"),
    path("registro/concluido/", views.registro_concluido, name="registro_concluido"),
    path("painel/", views.painel_usuarios, name="painel"),
    path("painel/<int:pk>/aprovar/", views.aprovar_usuario, name="aprovar"),
    path("painel/<int:pk>/reprovar/", views.reprovar_usuario, name="reprovar"),
    path("painel/<int:pk>/exigir-troca-senha/", views.exigir_troca_senha, name="exigir_troca_senha"),
    path("painel/<int:pk>/cancelar-troca-senha/", views.cancelar_troca_senha, name="cancelar_troca_senha"),
    path("painel/<int:pk>/senha-temporaria/", views.definir_senha_temporaria, name="senha_temporaria"),
    path("senha/", views.TrocarSenhaView.as_view(), name="trocar_senha"),
]
