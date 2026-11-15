"""Auxiliares compartilhados pelos testes."""
from django.contrib.auth import get_user_model
from django.test import override_settings

from .models import UserProfile

User = get_user_model()
SENHA = "Senha-Forte-123!"


def criar_usuario(username, aprovado=True):
    """Cria um usuário comum (aprovado por padrão) com senha conhecida."""
    user = User.objects.create_user(
        username=username, password=SENHA, email=f"{username}@exemplo.com"
    )
    if aprovado:
        UserProfile.objects.filter(user=user).update(status=UserProfile.Status.APPROVED)
    return user


def criar_admin(username="admin"):
    return User.objects.create_superuser(username, f"{username}@exemplo.com", SENHA)


# O AxesBackend exige `request` no login, e o client.login() dos testes não envia.
# Nos testes usamos só o backend de aprovação (o limite de tentativas é do Axes).
sem_axes = override_settings(
    AUTHENTICATION_BACKENDS=["accounts.backends.ApprovedUserBackend"],
    AXES_ENABLED=False,
)
