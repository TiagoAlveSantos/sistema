from datetime import datetime, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.testutils import SENHA, User, criar_admin, criar_usuario

from .models import Cliente, Produto, Prospeccao, Venda
from .services import registrar_venda


class IsolamentoTests(TestCase):
    def setUp(self):
        self.ana = criar_usuario("ana")
        self.bia = criar_usuario("bia")
        self.cliente_ana = Cliente.objects.create(usuario=self.ana, nome="Cliente da Ana")
        self.produto_ana = Produto.objects.create(
            usuario=self.ana,
            nome="Item da Ana",
            quantidade=5,
            preco_compra=Decimal("1.00"),
            preco_venda=Decimal("2.00"),
        )
        self.client.login(username="bia", password=SENHA)  # logada como Bia

    def test_listagens_nao_mostram_dados_de_outros(self):
        self.assertNotContains(self.client.get(reverse("gestao:cliente_list")), "Cliente da Ana")
        self.assertNotContains(self.client.get(reverse("gestao:produto_list")), "Item da Ana")

    def test_editar_registro_de_outro_retorna_404(self):
        url = reverse("gestao:cliente_update", args=[self.cliente_ana.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"nome": "Invadido"}).status_code, 404)
        self.cliente_ana.refresh_from_db()
        self.assertEqual(self.cliente_ana.nome, "Cliente da Ana")

        url = reverse("gestao:produto_update", args=[self.produto_ana.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_nao_cria_prospeccao_para_cliente_de_outro(self):
        resp = self.client.post(
            reverse("gestao:prospeccao_create"),
            {
                "cliente": self.cliente_ana.pk,
                "descricao": "x",
                "status": "nova",
                "data_contato": "2026-01-10",
            },
        )
        self.assertEqual(resp.status_code, 200)  # formulário inválido
        self.assertEqual(Prospeccao.objects.count(), 0)

    def test_nao_vende_item_ou_cliente_de_outro(self):
        cliente_bia = Cliente.objects.create(usuario=self.bia, nome="Cliente da Bia")
        resp = self.client.post(
            reverse("gestao:venda_create"),
            {
                "cliente": cliente_bia.pk,
                "produto": self.produto_ana.pk,
                "quantidade": 1,
                "preco_venda_praticado": "2.00",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Venda.objects.count(), 0)
        self.produto_ana.refresh_from_db()
        self.assertEqual(self.produto_ana.quantidade, 5)

    def test_registro_criado_pertence_ao_usuario_logado(self):
        self.client.post(
            reverse("gestao:cliente_create"),
            {"nome": "Novo", "usuario": self.ana.pk},  # tentativa de forjar o dono
        )
        self.assertEqual(Cliente.objects.get(nome="Novo").usuario, self.bia)

    def test_superusuario_nao_acessa_modulos_de_negocio(self):
        criar_admin()
        admin = Client()
        admin.login(username="admin", password=SENHA)
        for nome in [
            "gestao:cliente_list",
            "gestao:prospeccao_list",
            "gestao:produto_list",
            "gestao:venda_list",
            "gestao:venda_create",
        ]:
            resp = admin.get(reverse(nome))
            self.assertRedirects(
                resp, reverse("accounts:painel"), fetch_redirect_response=False
            )

    def test_anonimo_vai_para_login(self):
        resp = Client().get(reverse("gestao:cliente_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp["Location"])


class VendaTests(TestCase):
    def setUp(self):
        self.user = criar_usuario("ana")
        self.cliente = Cliente.objects.create(usuario=self.user, nome="Loja X")
        self.produto = Produto.objects.create(
            usuario=self.user,
            nome="Caneta",
            quantidade=10,
            preco_compra=Decimal("2.00"),
            preco_venda=Decimal("5.00"),
        )
        self.client.login(username="ana", password=SENHA)
        self.url = reverse("gestao:venda_create")

    def _post(self, quantidade, preco="6.00"):
        return self.client.post(
            self.url,
            {
                "cliente": self.cliente.pk,
                "produto": self.produto.pk,
                "quantidade": quantidade,
                "preco_venda_praticado": preco,
            },
        )

    def test_venda_debita_estoque_e_calcula_lucro(self):
        resp = self._post(3, "6.00")  # preço alterado (sugerido era 5,00)
        self.assertRedirects(resp, reverse("gestao:venda_list"))

        self.produto.refresh_from_db()
        self.assertEqual(self.produto.quantidade, 7)

        venda = Venda.objects.get()
        self.assertEqual(venda.usuario, self.user)
        self.assertEqual(venda.total, Decimal("18.00"))
        self.assertEqual(venda.lucro, Decimal("12.00"))  # (6 - 2) * 3

    def test_lucro_historico_nao_muda_se_custo_mudar_depois(self):
        self._post(1, "6.00")
        Produto.objects.filter(pk=self.produto.pk).update(preco_compra=Decimal("5.00"))
        self.assertEqual(Venda.objects.get().lucro, Decimal("4.00"))

    def test_estoque_insuficiente_nao_grava_nada(self):
        resp = self._post(11)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Estoque insuficiente")
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.quantidade, 10)
        self.assertEqual(Venda.objects.count(), 0)


class DashboardTests(TestCase):
    def setUp(self):
        self.user = criar_usuario("ana")
        self.c1 = Cliente.objects.create(usuario=self.user, nome="C1")
        self.c2 = Cliente.objects.create(usuario=self.user, nome="C2")
        self.produto = Produto.objects.create(
            usuario=self.user,
            nome="Item",
            quantidade=50,
            preco_compra=Decimal("10.00"),
            preco_venda=Decimal("15.00"),
        )
        self.client.login(username="ana", password=SENHA)

    def _vender(self, cliente, qtd, preco):
        return registrar_venda(
            usuario=self.user,
            cliente=cliente,
            produto=self.produto,
            quantidade=qtd,
            preco_venda_praticado=Decimal(preco),
        )

    def test_metricas_do_mes_atual(self):
        self._vender(self.c1, 2, "15.00")  # total 30, lucro 10
        self._vender(self.c1, 1, "12.00")  # total 12, lucro 2
        self._vender(self.c2, 1, "20.00")  # total 20, lucro 10
        Prospeccao.objects.create(
            usuario=self.user,
            cliente=self.c1,
            descricao="Ligar",
            data_contato=timezone.localdate(),
        )

        ctx = self.client.get(reverse("gestao:dashboard")).context
        self.assertEqual(ctx["total_vendas"], Decimal("62.00"))
        self.assertEqual(ctx["total_lucro"], Decimal("22.00"))
        self.assertEqual(ctx["qtd_prospeccoes"], 1)
        self.assertEqual(ctx["total_clientes"], 2)
        self.assertEqual(ctx["clientes_compradores"], 2)

    def test_dashboard_vazio_mostra_zeros(self):
        ctx = self.client.get(reverse("gestao:dashboard")).context
        self.assertEqual(ctx["total_vendas"], Decimal("0.00"))
        self.assertEqual(ctx["clientes_compradores"], 0)

    def test_seletor_de_mes_respeita_criacao_da_conta(self):
        hoje = timezone.localdate()
        este_mes = hoje.replace(day=1)
        mes_anterior = (este_mes - timedelta(days=1)).replace(day=1)

        # Conta criada no mês anterior; venda feita no meio do mês anterior.
        User.objects.filter(pk=self.user.pk).update(
            date_joined=timezone.make_aware(
                datetime(mes_anterior.year, mes_anterior.month, 2, 10, 0)
            )
        )
        venda = self._vender(self.c1, 1, "15.00")
        Venda.objects.filter(pk=venda.pk).update(
            data_venda=timezone.make_aware(
                datetime(mes_anterior.year, mes_anterior.month, 15, 12, 0)
            )
        )

        url = reverse("gestao:dashboard")
        atual = self.client.get(url).context
        self.assertEqual(atual["mes_selecionado"], este_mes)
        self.assertEqual(atual["total_vendas"], Decimal("0.00"))
        self.assertEqual(len(atual["meses"]), 2)

        anterior = self.client.get(url, {"mes": mes_anterior.strftime("%Y-%m")}).context
        self.assertEqual(anterior["mes_selecionado"], mes_anterior)
        self.assertEqual(anterior["total_vendas"], Decimal("15.00"))
        self.assertEqual(anterior["clientes_compradores"], 1)

        # Mês anterior à criação da conta (ou lixo) cai no mês atual.
        antigo = (mes_anterior - timedelta(days=1)).replace(day=1)
        fora = self.client.get(url, {"mes": antigo.strftime("%Y-%m")}).context
        self.assertEqual(fora["mes_selecionado"], este_mes)
        lixo = self.client.get(url, {"mes": "abc"}).context
        self.assertEqual(lixo["mes_selecionado"], este_mes)
