from django.contrib import messages

from accounts.permissions import UsuarioComumMixin


class DonoQuerysetMixin(UsuarioComumMixin):
    """
    Exige login (e bloqueia superusuário) e restringe o queryset aos registros
    do usuário logado. Registro de outro usuário => 404 (nem confirma que existe).
    """

    def get_queryset(self):
        return super().get_queryset().do_usuario(self.request.user)


class DonoFormMixin(DonoQuerysetMixin):
    """Para Create/UpdateView: injeta o usuário no form e grava o dono no objeto."""

    mensagem_sucesso = ""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["usuario"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.usuario = self.request.user  # nunca vem do POST
        resposta = super().form_valid(form)
        if self.mensagem_sucesso:
            messages.success(self.request, self.mensagem_sucesso)
        return resposta
