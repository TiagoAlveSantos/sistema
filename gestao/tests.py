from datetime import datetime, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.testutils import SENHA, User, criar_admin, criar_usuario, sem_axes

from .models import Cliente, Produto, Prospeccao, Venda
from .services import registrar_venda


def agora_str():
    """Data/hora atual no formato que o formulário de venda envia (AAAA-MM-DD HH:MM)."""
    return timezone.localtime().strftime("%Y-%m-%d %H:%M")


# ==========================================================================
# Isolamento entre usuários
# ==========================================================================
@sem_axes
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

    def test_editar_ou_reverter_venda_de_outro_retorna_404(self):
        venda = registrar_venda(
            usuario=self.ana,
            cliente=self.cliente_ana,
            produto=self.produto_ana,
            quantidade=1,
            preco_venda_praticado=Decimal("2.00"),
        )
        for nome in ("gestao:venda_update", "gestao:venda_delete"):
            self.assertEqual(self.client.get(reverse(nome, args=[venda.pk])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("gestao:venda_delete", args=[venda.pk])).status_code, 404
        )
        self.assertTrue(Venda.objects.filter(pk=venda.pk).exists())

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
                "data_venda": agora_str(),
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


# ==========================================================================
# Clientes (busca e CPF)
# ==========================================================================
@sem_axes
class ClienteTests(TestCase):
    CPF_VALIDO = "529.982.247-25"

    def setUp(self):
        self.user = criar_usuario("ana")
        self.client.login(username="ana", password=SENHA)
        self.url = reverse("gestao:cliente_create")

    def test_busca_por_nome_e_por_cpf(self):
        Cliente.objects.create(usuario=self.user, nome="Maria Souza", cpf=self.CPF_VALIDO)
        Cliente.objects.create(usuario=self.user, nome="João Lima")
        lista = reverse("gestao:cliente_list")

        resp = self.client.get(lista, {"q": "Maria"})
        self.assertContains(resp, "Maria Souza")
        self.assertNotContains(resp, "João Lima")

        resp = self.client.get(lista, {"q": "529.982"})
        self.assertContains(resp, "Maria Souza")
        self.assertNotContains(resp, "João Lima")

    def test_cpf_valido_e_normalizado(self):
        self.client.post(self.url, {"nome": "Ana", "cpf": "52998224725"})
        self.assertEqual(Cliente.objects.get(nome="Ana").cpf, self.CPF_VALIDO)

    def test_cpf_invalido_e_rejeitado(self):
        for cpf in ("111.111.111-11", "123", "529.982.247-26"):
            resp = self.client.post(self.url, {"nome": "Teste", "cpf": cpf})
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "CPF inválido")
        self.assertEqual(Cliente.objects.count(), 0)

    def test_cpf_em_branco_e_permitido(self):
        self.client.post(self.url, {"nome": "Sem CPF", "cpf": ""})
        self.assertIsNone(Cliente.objects.get(nome="Sem CPF").cpf)

    def test_cpf_duplicado_para_o_mesmo_usuario_e_rejeitado(self):
        Cliente.objects.create(usuario=self.user, nome="Primeiro", cpf=self.CPF_VALIDO)
        resp = self.client.post(self.url, {"nome": "Segundo", "cpf": self.CPF_VALIDO})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "já tem um cliente")
        self.assertEqual(Cliente.objects.count(), 1)

    def test_mesmo_cpf_em_outro_usuario_e_permitido(self):
        outra = criar_usuario("bia")
        Cliente.objects.create(usuario=outra, nome="Da Bia", cpf=self.CPF_VALIDO)
        self.client.post(self.url, {"nome": "Da Ana", "cpf": self.CPF_VALIDO})
        self.assertTrue(Cliente.objects.filter(usuario=self.user, nome="Da Ana").exists())


# ==========================================================================
# Nova venda
# ==========================================================================
@sem_axes
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

    def _post(self, quantidade, preco="6.00", data=None):
        return self.client.post(
            self.url,
            {
                "cliente": self.cliente.pk,
                "produto": self.produto.pk,
                "quantidade": quantidade,
                "preco_venda_praticado": preco,
                "data_venda": data or agora_str(),
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

    def test_venda_retroativa_grava_a_data_informada(self):
        resp = self._post(1, "6.00", data="2026-01-10 14:30")
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        esperado = timezone.make_aware(datetime(2026, 1, 10, 14, 30))
        self.assertEqual(Venda.objects.get().data_venda, esperado)

    def test_data_futura_e_rejeitada(self):
        amanha = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        resp = self._post(1, "6.00", data=amanha)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ser no futuro")
        self.assertEqual(Venda.objects.count(), 0)

    def test_filtro_de_cliente_invalido_nao_quebra_a_listagem(self):
        resp = self.client.get(reverse("gestao:venda_list"), {"cliente": "abc"})
        self.assertEqual(resp.status_code, 200)

    def test_filtro_por_cliente(self):
        outro = Cliente.objects.create(usuario=self.user, nome="Loja Y")
        self._post(1)
        registrar_venda(
            usuario=self.user,
            cliente=outro,
            produto=self.produto,
            quantidade=1,
            preco_venda_praticado=Decimal("5.00"),
        )
        resp = self.client.get(reverse("gestao:venda_list"), {"cliente": outro.pk})
        self.assertEqual(len(resp.context["object_list"]), 1)
        self.assertEqual(resp.context["object_list"][0].cliente, outro)


# ==========================================================================
# Editar venda (produto e custo travados, estoque ajustado)
# ==========================================================================
@sem_axes
class VendaEdicaoTests(TestCase):
    DATA_ORIGINAL = datetime(2026, 1, 10, 15, 30, 45)  # com segundos, de propósito

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
        # Vende 3 -> estoque passa a 7
        self.venda = registrar_venda(
            usuario=self.user,
            cliente=self.cliente,
            produto=self.produto,
            quantidade=3,
            preco_venda_praticado=Decimal("6.00"),
            data_venda=timezone.make_aware(self.DATA_ORIGINAL),
        )
        self.url = reverse("gestao:venda_update", args=[self.venda.pk])

    def _editar(self, quantidade, preco="6.00", data="2026-01-10 15:30", produto=None):
        return self.client.post(
            self.url,
            {
                "cliente": self.cliente.pk,
                "produto": (produto or self.produto).pk,
                "quantidade": quantidade,
                "preco_venda_praticado": preco,
                "data_venda": data,
            },
        )

    def _estoque(self):
        self.produto.refresh_from_db()
        return self.produto.quantidade

    def test_tela_de_edicao_mostra_a_data_da_venda(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Editar venda")
        self.assertContains(resp, 'value="2026-01-10 15:30"')

    def test_aumentar_quantidade_debita_a_diferenca_do_estoque(self):
        resp = self._editar(5)
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        self.assertEqual(self._estoque(), 5)  # 7 - 2

        self.venda.refresh_from_db()
        self.assertEqual(self.venda.quantidade, 5)
        self.assertEqual(self.venda.total, Decimal("30.00"))
        self.assertEqual(self.venda.lucro, Decimal("20.00"))  # (6 - 2) * 5

    def test_diminuir_quantidade_devolve_ao_estoque(self):
        self._editar(2)
        self.assertEqual(self._estoque(), 8)  # 7 + 1
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.lucro, Decimal("8.00"))

    def test_pode_usar_exatamente_todo_o_estoque_disponivel(self):
        self._editar(10)  # 7 em estoque + 3 que a venda já usa
        self.assertEqual(self._estoque(), 0)

    def test_acima_do_disponivel_e_rejeitado_sem_mexer_no_estoque(self):
        resp = self._editar(11)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Estoque insuficiente")
        self.assertEqual(self._estoque(), 7)
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.quantidade, 3)

    def test_sem_estoque_a_quantidade_fica_bloqueada(self):
        Produto.objects.filter(pk=self.produto.pk).update(quantidade=0)
        resp = self.client.get(self.url)
        self.assertTrue(resp.context["form"].fields["quantidade"].disabled)

        self._editar(9)  # tentativa de burlar: o servidor ignora o valor
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.quantidade, 3)
        self.assertEqual(self._estoque(), 0)

    def test_produto_nao_pode_ser_trocado(self):
        outro = Produto.objects.create(
            usuario=self.user,
            nome="Lápis",
            quantidade=50,
            preco_compra=Decimal("1.00"),
            preco_venda=Decimal("2.00"),
        )
        self._editar(3, produto=outro)
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.produto, self.produto)
        outro.refresh_from_db()
        self.assertEqual(outro.quantidade, 50)

    def test_data_original_e_mantida_com_segundos_quando_nao_alterada(self):
        self._editar(3, data="2026-01-10 15:30")  # mesmo minuto da original
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.data_venda, timezone.make_aware(self.DATA_ORIGINAL))

    def test_data_pode_ser_alterada(self):
        self._editar(3, data="2026-01-11 10:00")
        self.venda.refresh_from_db()
        self.assertEqual(
            self.venda.data_venda, timezone.make_aware(datetime(2026, 1, 11, 10, 0))
        )

    def test_custo_historico_e_preservado_ao_editar(self):
        Produto.objects.filter(pk=self.produto.pk).update(preco_compra=Decimal("5.00"))
        self._editar(3, preco="7.00")
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.preco_compra_unitario, Decimal("2.00"))
        self.assertEqual(self.venda.lucro, Decimal("15.00"))  # (7 - 2) * 3


# ==========================================================================
# Reverter (estornar) venda
# ==========================================================================
@sem_axes
class VendaReversaoTests(TestCase):
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
        self.venda = registrar_venda(
            usuario=self.user,
            cliente=self.cliente,
            produto=self.produto,
            quantidade=4,
            preco_venda_praticado=Decimal("5.00"),
        )

    def test_reverter_devolve_o_estoque_e_apaga_a_venda(self):
        self.produto.refresh_from_db()
        self.assertEqual(self.produto.quantidade, 6)

        resp = self.client.post(reverse("gestao:venda_delete", args=[self.venda.pk]))
        self.assertRedirects(resp, reverse("gestao:venda_list"))

        self.produto.refresh_from_db()
        self.assertEqual(self.produto.quantidade, 10)
        self.assertFalse(Venda.objects.filter(pk=self.venda.pk).exists())

    def test_tela_de_confirmacao_nao_altera_nada(self):
        resp = self.client.get(reverse("gestao:venda_delete", args=[self.venda.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Venda.objects.filter(pk=self.venda.pk).exists())


# ==========================================================================
# Dashboard
# ==========================================================================
@sem_axes
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

    def test_reverter_venda_atualiza_as_metricas(self):
        venda = self._vender(self.c1, 2, "15.00")
        self.client.post(reverse("gestao:venda_delete", args=[venda.pk]))
        ctx = self.client.get(reverse("gestao:dashboard")).context
        self.assertEqual(ctx["total_vendas"], Decimal("0.00"))

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
