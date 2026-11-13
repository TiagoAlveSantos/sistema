from django.contrib.auth.backends import ModelBackend

from .permissions import is_user_approved


class ApprovedUserBackend(ModelBackend):
    """
    Só autentica usuários ativos E aprovados.

    `ModelBackend.get_user()` também chama `user_can_authenticate()`, então uma
    sessão já aberta deixa de valer assim que o administrador reprova o usuário.
    """

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and is_user_approved(user)
