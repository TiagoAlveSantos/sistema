from django.test import Client, TestCase
from django.urls import reverse

from .models import UserProfile
from .testutils import SENHA, User, criar_admin, criar_usuario


class RegistroEAprovacaoTests(TestCase):
    def test_registro_cria_usuario_pendente(self):
        resp = self.client.post(
            reverse("accounts:registro"),
            {
                "username": "maria",
                "first_name": "Maria",
                "email": "maria@exemplo.com",
                "password1": SENHA,
                "password2": SENHA,
            },
        )
        self.assertRedirects(resp, reverse("accounts:registro_concluido"))
        user = User.objects.get(username="maria")
        self.assertEqual(user.profile.status, UserProfile.Status.PENDING)
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_registro_nao_aceita_campos_de_privilegio(self):
        self.client.post(
            reverse("accounts:registro"),
            {
                "username": "hacker",
                "first_name": "H",
                "email": "h@exemplo.com",
                "password1": SENHA,
                "password2": SENHA,
                "is_superuser": "on",
                "is_staff": "on",
            },
        )
        user = User.objects.get(username="hacker")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)

    def test_pendente_nao_consegue_logar(self):
        criar_usuario("joao", aprovado=False)
        resp = self.client.post(
            reverse("accounts:login"), {"username": "joao", "password": SENHA}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "aguardando aprovação")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_senha_errada_nao_revela_status(self):
        criar_usuario("joao", aprovado=False)
        resp = self.client.post(
            reverse("accounts:login"), {"username": "joao", "password": "errada"}
        )
        self.assertNotContains(resp, "aguardando aprovação")

    def test_aprovado_consegue_logar(self):
        criar_usuario("ana")
        resp = self.client.post(
            reverse("accounts:login"), {"username": "ana", "password": SENHA}
        )
        self.assertRedirects(
            resp, reverse("gestao:dashboard"), fetch_redirect_response=False
        )

    def test_superusuario_nasce_aprovado(self):
        admin = criar_admin()
        self.assertTrue(admin.profile.is_approved)
        self.assertTrue(self.client.login(username="admin", password=SENHA))

    def test_usuario_comum_nao_acessa_painel(self):
        criar_usuario("ana")
        self.client.login(username="ana", password=SENHA)
        self.assertEqual(self.client.get(reverse("accounts:painel")).status_code, 403)

    def test_admin_aprova_e_reprova(self):
        criar_admin()
        pendente = criar_usuario("joao", aprovado=False)
        self.client.login(username="admin", password=SENHA)

        self.client.post(reverse("accounts:aprovar", args=[pendente.pk]))
        self.assertEqual(
            UserProfile.objects.get(user=pendente).status, UserProfile.Status.APPROVED
        )
        self.client.post(reverse("accounts:reprovar", args=[pendente.pk]))
        self.assertEqual(
            UserProfile.objects.get(user=pendente).status, UserProfile.Status.REJECTED
        )

    def test_aprovar_exige_post(self):
        criar_admin()
        pendente = criar_usuario("joao", aprovado=False)
        self.client.login(username="admin", password=SENHA)
        resp = self.client.get(reverse("accounts:aprovar", args=[pendente.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_reprovar_derruba_sessao_ativa(self):
        usuario = criar_usuario("ana")
        cliente_web = Client()
        cliente_web.login(username="ana", password=SENHA)
        self.assertEqual(
            cliente_web.get(reverse("gestao:cliente_list")).status_code, 200
        )

        UserProfile.objects.filter(user=usuario).update(
            status=UserProfile.Status.REJECTED
        )
        resp = cliente_web.get(reverse("gestao:cliente_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp["Location"])
