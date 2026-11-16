from datetime import timedelta

from axes.models import AccessAttempt
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .testutils import SENHA, criar_admin, criar_usuario, sem_axes


def tentativa(username, falhas=5, ip="203.0.113.7", minutos_atras=1):
    t = AccessAttempt.objects.create(
        username=username,
        ip_address=ip,
        user_agent="teste",
        http_accept="*/*",
        path_info="/contas/login/",
        get_data="",
        post_data="",
        failures_since_start=falhas,
    )
    # attempt_time é automático: ajusta para simular o passado
    AccessAttempt.objects.filter(pk=t.pk).update(
        attempt_time=timezone.now() - timedelta(minutes=minutos_atras)
    )
    return t


@sem_axes
class BloqueiosTests(TestCase):
    def setUp(self):
        self.admin = criar_admin()
        self.ana = criar_usuario("ana")
        self.adm = Client()
        self.adm.login(username="admin", password=SENHA)
        self.url = reverse("accounts:bloqueios")

    def test_pagina_vazia(self):
        resp = self.adm.get(self.url)
        self.assertContains(resp, "Ninguém está bloqueado")

    def test_lista_usuario_bloqueado_com_horario_de_liberacao(self):
        tentativa("ana", falhas=5)
        resp = self.adm.get(self.url)
        self.assertContains(resp, "ana")
        self.assertContains(resp, "Bloqueado")
        self.assertEqual(resp.context["total_bloqueados"], 1)

    def test_abaixo_do_limite_e_apenas_contagem(self):
        tentativa("ana", falhas=2)
        resp = self.adm.get(self.url)
        self.assertContains(resp, "Em contagem")
        self.assertEqual(resp.context["total_bloqueados"], 0)

    def test_bloqueio_antigo_aparece_como_expirado(self):
        tentativa("ana", falhas=5, minutos_atras=45)  # além dos 30 min
        resp = self.adm.get(self.url)
        self.assertContains(resp, "Expirado")
        self.assertEqual(resp.context["total_bloqueados"], 0)

    def test_desbloquear_um(self):
        a = tentativa("ana")
        b = tentativa("bia", ip="198.51.100.2")
        resp = self.adm.post(reverse("accounts:desbloquear", args=[a.pk]))
        self.assertRedirects(resp, self.url)
        self.assertFalse(AccessAttempt.objects.filter(pk=a.pk).exists())
        self.assertTrue(AccessAttempt.objects.filter(pk=b.pk).exists())

    def test_desbloquear_todos(self):
        tentativa("ana")
        tentativa("bia", ip="198.51.100.2")
        self.adm.post(reverse("accounts:desbloquear_todos"))
        self.assertEqual(AccessAttempt.objects.count(), 0)

    def test_desbloquear_registro_inexistente_nao_quebra(self):
        resp = self.adm.post(reverse("accounts:desbloquear", args=[99999]))
        self.assertRedirects(resp, self.url)

    def test_acoes_exigem_post(self):
        t = tentativa("ana")
        self.assertEqual(self.adm.get(reverse("accounts:desbloquear", args=[t.pk])).status_code, 405)
        self.assertEqual(self.adm.get(reverse("accounts:desbloquear_todos")).status_code, 405)
        self.assertTrue(AccessAttempt.objects.filter(pk=t.pk).exists())

    def test_usuario_comum_e_anonimo_nao_acessam(self):
        t = tentativa("ana")
        c = Client()
        c.login(username="ana", password=SENHA)
        self.assertEqual(c.get(self.url).status_code, 403)
        self.assertEqual(c.post(reverse("accounts:desbloquear", args=[t.pk])).status_code, 403)
        self.assertEqual(c.post(reverse("accounts:desbloquear_todos")).status_code, 403)
        self.assertTrue(AccessAttempt.objects.filter(pk=t.pk).exists())
        anon = Client().get(self.url)
        self.assertIn(anon.status_code, (302, 403))
