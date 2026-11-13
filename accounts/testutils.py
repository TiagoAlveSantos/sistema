"""Auxiliares compartilhados pelos testes."""
from django.contrib.auth import get_user_model

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
