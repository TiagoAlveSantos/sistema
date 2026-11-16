import io
import json
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from . import captcha
from .models import UserProfile
from .testutils import SENHA, User, criar_admin, criar_usuario, sem_axes


@sem_axes
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


class ConfiguracaoSegurancaTests(TestCase):
    """Garante que ninguém reabra o contorno da aprovação por engano."""

    def test_modelbackend_puro_nao_pode_estar_configurado(self):
        from django.conf import settings

        self.assertNotIn(
            "django.contrib.auth.backends.ModelBackend", settings.AUTHENTICATION_BACKENDS
        )
        self.assertIn(
            "accounts.backends.ApprovedUserBackend", settings.AUTHENTICATION_BACKENDS
        )


NOVA_SENHA = "Nova-Senha-456!"


@sem_axes
class TrocaDeSenhaTests(TestCase):
    def setUp(self):
        self.admin = criar_admin()
        self.ana = criar_usuario("ana")
        self.url_troca = reverse("accounts:trocar_senha")

    def _exigir(self):
        c = Client()
        c.login(username="admin", password=SENHA)
        return c.post(reverse("accounts:exigir_troca_senha", args=[self.ana.pk]))

    def _logar_ana(self):
        c = Client()
        self.assertTrue(c.login(username="ana", password=SENHA))
        return c

    def test_admin_exige_a_troca_e_marca_o_perfil(self):
        resp = self._exigir()
        self.assertEqual(resp.status_code, 302)
        self.ana.profile.refresh_from_db()
        self.assertTrue(self.ana.profile.must_change_password)

    def test_usuario_comum_nao_pode_exigir_troca_de_ninguem(self):
        c = self._logar_ana()
        outra = criar_usuario("bia")
        resp = c.post(reverse("accounts:exigir_troca_senha", args=[outra.pk]))
        self.assertEqual(resp.status_code, 403)
        outra.profile.refresh_from_db()
        self.assertFalse(outra.profile.must_change_password)

    def test_exigir_troca_exige_post(self):
        c = Client()
        c.login(username="admin", password=SENHA)
        resp = c.get(reverse("accounts:exigir_troca_senha", args=[self.ana.pk]))
        self.assertEqual(resp.status_code, 405)

    def test_admin_nao_altera_outro_administrador(self):
        outro = criar_admin("admin2")
        c = Client()
        c.login(username="admin", password=SENHA)
        resp = c.post(reverse("accounts:exigir_troca_senha", args=[outro.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_com_troca_exigida_o_sistema_redireciona_para_a_troca(self):
        self._exigir()
        c = self._logar_ana()
        for nome in ("gestao:dashboard", "gestao:cliente_list", "gestao:venda_list"):
            resp = c.get(reverse(nome))
            self.assertRedirects(resp, self.url_troca, fetch_redirect_response=False)
        resp = c.get(self.url_troca)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "O administrador pediu")

    def test_com_troca_exigida_ainda_pode_sair(self):
        self._exigir()
        c = self._logar_ana()
        resp = c.post(reverse("accounts:logout"))
        self.assertRedirects(resp, reverse("accounts:login"), fetch_redirect_response=False)

    def test_trocar_a_senha_libera_o_acesso_e_mantem_o_login(self):
        self._exigir()
        c = self._logar_ana()
        resp = c.post(
            self.url_troca,
            {"old_password": SENHA, "new_password1": NOVA_SENHA, "new_password2": NOVA_SENHA},
        )
        self.assertRedirects(resp, reverse("gestao:dashboard"), fetch_redirect_response=False)
        self.ana.profile.refresh_from_db()
        self.assertFalse(self.ana.profile.must_change_password)
        self.assertEqual(c.get(reverse("gestao:dashboard")).status_code, 200)  # segue logada

        # senha nova funciona; a antiga não
        self.assertTrue(Client().login(username="ana", password=NOVA_SENHA))
        self.assertFalse(Client().login(username="ana", password=SENHA))

    def test_senha_atual_errada_nao_troca_e_continua_exigindo(self):
        self._exigir()
        c = self._logar_ana()
        resp = c.post(
            self.url_troca,
            {"old_password": "errada", "new_password1": NOVA_SENHA, "new_password2": NOVA_SENHA},
        )
        self.assertEqual(resp.status_code, 200)
        self.ana.profile.refresh_from_db()
        self.assertTrue(self.ana.profile.must_change_password)
        self.assertTrue(Client().login(username="ana", password=SENHA))  # senha antiga segue valendo

    def test_nova_senha_igual_a_atual_e_rejeitada(self):
        self._exigir()
        c = self._logar_ana()
        resp = c.post(
            self.url_troca,
            {"old_password": SENHA, "new_password1": SENHA, "new_password2": SENHA},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "diferente da atual")
        self.ana.profile.refresh_from_db()
        self.assertTrue(self.ana.profile.must_change_password)

    def test_senha_fraca_e_rejeitada(self):
        c = self._logar_ana()
        resp = c.post(
            self.url_troca,
            {"old_password": SENHA, "new_password1": "12345678", "new_password2": "12345678"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Client().login(username="ana", password=SENHA))

    def test_admin_pode_cancelar_a_exigencia(self):
        self._exigir()
        c = Client()
        c.login(username="admin", password=SENHA)
        c.post(reverse("accounts:cancelar_troca_senha", args=[self.ana.pk]))
        self.ana.profile.refresh_from_db()
        self.assertFalse(self.ana.profile.must_change_password)
        self.assertEqual(self._logar_ana().get(reverse("gestao:dashboard")).status_code, 200)

    def test_troca_voluntaria_funciona_sem_exigencia(self):
        c = self._logar_ana()
        self.assertEqual(c.get(self.url_troca).status_code, 200)
        c.post(
            self.url_troca,
            {"old_password": SENHA, "new_password1": NOVA_SENHA, "new_password2": NOVA_SENHA},
        )
        self.assertTrue(Client().login(username="ana", password=NOVA_SENHA))

    def test_anonimo_vai_para_o_login(self):
        resp = Client().get(self.url_troca)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp["Location"])

    def test_painel_mostra_o_estado_da_troca(self):
        c = Client()
        c.login(username="admin", password=SENHA)
        url = reverse("accounts:painel") + "?status=approved"
        self.assertContains(c.get(url), "Exigir troca de senha")
        self._exigir()
        resp = c.get(url)
        self.assertContains(resp, "Troca de senha pendente")
        self.assertContains(resp, "Cancelar troca de senha")


@sem_axes
class SenhaTemporariaTests(TestCase):
    def setUp(self):
        self.admin = criar_admin()
        self.ana = criar_usuario("ana")
        self.url = reverse("accounts:senha_temporaria", args=[self.ana.pk])
        self.adm = Client()
        self.adm.login(username="admin", password=SENHA)

    def test_admin_define_senha_temporaria_e_exige_a_troca(self):
        resp = self.adm.post(
            self.url, {"new_password1": "Temp-Senha-789!", "new_password2": "Temp-Senha-789!"}
        )
        self.assertRedirects(resp, reverse("accounts:painel"), fetch_redirect_response=False)
        self.ana.profile.refresh_from_db()
        self.assertTrue(self.ana.profile.must_change_password)
        self.assertTrue(Client().login(username="ana", password="Temp-Senha-789!"))
        self.assertFalse(Client().login(username="ana", password=SENHA))

    def test_com_a_temporaria_o_usuario_e_obrigado_a_trocar(self):
        self.adm.post(
            self.url, {"new_password1": "Temp-Senha-789!", "new_password2": "Temp-Senha-789!"}
        )
        c = Client()
        c.login(username="ana", password="Temp-Senha-789!")
        self.assertRedirects(
            c.get(reverse("gestao:dashboard")),
            reverse("accounts:trocar_senha"),
            fetch_redirect_response=False,
        )
        resp = c.post(
            reverse("accounts:trocar_senha"),
            {
                "old_password": "Temp-Senha-789!",
                "new_password1": NOVA_SENHA,
                "new_password2": NOVA_SENHA,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(c.get(reverse("gestao:dashboard")).status_code, 200)
        self.assertTrue(Client().login(username="ana", password=NOVA_SENHA))

    def test_sessao_aberta_do_usuario_cai_ao_definir_a_temporaria(self):
        c = Client()
        c.login(username="ana", password=SENHA)
        self.assertEqual(c.get(reverse("gestao:dashboard")).status_code, 200)
        self.adm.post(
            self.url, {"new_password1": "Temp-Senha-789!", "new_password2": "Temp-Senha-789!"}
        )
        resp = c.get(reverse("gestao:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp["Location"])

    def test_senhas_diferentes_ou_fracas_sao_rejeitadas(self):
        resp = self.adm.post(
            self.url, {"new_password1": "Temp-Senha-789!", "new_password2": "outra"}
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.adm.post(self.url, {"new_password1": "12345678", "new_password2": "12345678"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Client().login(username="ana", password=SENHA))  # nada mudou
        self.ana.profile.refresh_from_db()
        self.assertFalse(self.ana.profile.must_change_password)

    def test_usuario_comum_nao_acessa(self):
        c = Client()
        c.login(username="ana", password=SENHA)
        self.assertEqual(c.get(self.url).status_code, 403)
        outra = criar_usuario("bia")
        resp = c.post(
            reverse("accounts:senha_temporaria", args=[outra.pk]),
            {"new_password1": "Temp-Senha-789!", "new_password2": "Temp-Senha-789!"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Client().login(username="bia", password=SENHA))

    def test_nao_define_senha_de_administrador(self):
        outro = criar_admin("admin2")
        resp = self.adm.get(reverse("accounts:senha_temporaria", args=[outro.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_painel_mostra_o_botao(self):
        resp = self.adm.get(reverse("accounts:painel") + "?status=approved")
        self.assertContains(resp, "Definir senha temporária")


# ==========================================================================
# Captcha do cadastro (Cloudflare Turnstile)
# ==========================================================================
DADOS_REGISTRO = {
    "username": "maria",
    "first_name": "Maria",
    "email": "maria@exemplo.com",
    "password1": SENHA,
    "password2": SENHA,
}
CHAVES = dict(TURNSTILE_SITE_KEY="site-123", TURNSTILE_SECRET_KEY="segredo-456")


@sem_axes
class CaptchaTests(TestCase):
    url = "/contas/registro/"

    def test_sem_chaves_o_captcha_fica_desligado(self):
        self.assertFalse(captcha.captcha_ativo())
        resp = self.client.get(self.url)
        self.assertNotContains(resp, "cf-turnstile")
        self.client.post(self.url, DADOS_REGISTRO)
        self.assertTrue(User.objects.filter(username="maria").exists())

    @override_settings(**CHAVES)
    def test_com_chaves_o_widget_aparece(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "cf-turnstile")
        self.assertContains(resp, "site-123")
        self.assertContains(resp, "challenges.cloudflare.com")

    @override_settings(**CHAVES)
    def test_sem_token_o_cadastro_e_recusado(self):
        resp = self.client.post(self.url, DADOS_REGISTRO)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não é um robô")
        self.assertFalse(User.objects.filter(username="maria").exists())

    @override_settings(**CHAVES)
    def test_token_recusado_pelo_cloudflare_bloqueia(self):
        with mock.patch("accounts.captcha.verificar", return_value=False):
            resp = self.client.post(self.url, {**DADOS_REGISTRO, "cf-turnstile-response": "x"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="maria").exists())

    @override_settings(**CHAVES)
    def test_token_aprovado_permite_o_cadastro(self):
        with mock.patch("accounts.captcha.verificar", return_value=True) as m:
            resp = self.client.post(self.url, {**DADOS_REGISTRO, "cf-turnstile-response": "tok"})
        self.assertRedirects(resp, reverse("accounts:registro_concluido"))
        m.assert_called_once_with("tok")
        self.assertTrue(User.objects.filter(username="maria").exists())

    @override_settings(**CHAVES)
    def test_formulario_invalido_nao_chama_o_cloudflare(self):
        with mock.patch("accounts.captcha.verificar") as m:
            self.client.post(self.url, {**DADOS_REGISTRO, "password2": "diferente"})
        m.assert_not_called()

    @override_settings(**CHAVES)
    def test_verificar_trata_falha_de_rede_como_recusa(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("sem rede")):
            self.assertFalse(captcha.verificar("tok"))
        self.assertFalse(captcha.verificar(""))

    @override_settings(**CHAVES)
    def test_verificar_aceita_resposta_de_sucesso(self):
        falsa = mock.MagicMock()
        falsa.__enter__.return_value = io.BytesIO(json.dumps({"success": True}).encode())
        with mock.patch("urllib.request.urlopen", return_value=falsa):
            self.assertTrue(captcha.verificar("tok"))
        falsa.__enter__.return_value = io.BytesIO(json.dumps({"success": False}).encode())
        with mock.patch("urllib.request.urlopen", return_value=falsa):
            self.assertFalse(captcha.verificar("tok"))
