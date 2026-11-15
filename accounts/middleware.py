from django.shortcuts import redirect
from django.urls import reverse


class TrocaSenhaObrigatoriaMiddleware:
    """
    Se o administrador exigiu a troca de senha, o usuário só enxerga a tela de
    troca (e o logout) até definir uma nova senha. Vale no próximo acesso,
    inclusive para sessões já abertas.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not user.is_superuser
            and self._precisa_trocar(user)
            and request.path
            not in (reverse("accounts:trocar_senha"), reverse("accounts:logout"))
        ):
            return redirect("accounts:trocar_senha")
        return self.get_response(request)

    @staticmethod
    def _precisa_trocar(user):
        perfil = getattr(user, "profile", None)  # sem perfil => não exige
        return bool(perfil and perfil.must_change_password)
