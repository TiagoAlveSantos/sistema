from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import UserProfile
from .permissions import is_user_approved

User = get_user_model()


class BootstrapFormMixin:
    """Aplica as classes do Bootstrap 5 em todos os campos do formulário."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            css = "form-select" if isinstance(widget, forms.Select) else "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()


class RegistroForm(BootstrapFormMixin, UserCreationForm):
    first_name = forms.CharField(label="Nome completo", max_length=150)
    email = forms.EmailField(label="E-mail")

    class Meta(UserCreationForm.Meta):
        model = User
        # Só estes campos vêm do formulário: is_staff / is_superuser / perfil
        # jamais podem ser injetados pelo POST.
        fields = ("username", "first_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Este e-mail já está cadastrado.")
        return email


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    """Login com mensagem clara para contas pendentes ou reprovadas."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "pendente": "Sua conta ainda está aguardando aprovação do administrador.",
        "reprovado": "Seu cadastro não foi aprovado. Entre em contato com o administrador.",
    }

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError as erro:
            # Só revela o motivo se usuário E senha estiverem corretos; assim
            # não há como descobrir se um usuário existe ou não.
            username = self.cleaned_data.get("username")
            password = self.cleaned_data.get("password")
            if username and password:
                usuario = User._default_manager.filter(
                    **{User.USERNAME_FIELD: username}
                ).first()
                if (
                    usuario
                    and usuario.is_active
                    and usuario.check_password(password)
                    and not is_user_approved(usuario)
                ):
                    perfil = UserProfile.objects.filter(user=usuario).first()
                    rejeitado = (
                        perfil is not None
                        and perfil.status == UserProfile.Status.REJECTED
                    )
                    codigo = "reprovado" if rejeitado else "pendente"
                    raise forms.ValidationError(
                        self.error_messages[codigo], code=codigo
                    ) from None
            raise erro
