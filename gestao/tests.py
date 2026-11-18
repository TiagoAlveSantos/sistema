from datetime import datetime, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.testutils import SENHA, criar_admin, criar_usuario, sem_axes

from .models import Cliente, ItemVenda, Pagamento, Produto, Prospeccao, Venda
from .services import VendaInvalida, registrar_venda


def agora_str():
    """Data/hora atual no formato que o formulário de venda envia (AAAA-MM-DD HH:MM)."""
    return timezone.localtime().strftime("%Y-%m-%d %H:%M")


def item(produto, quantidade, preco):
    """Linha de venda no formato esperado por registrar_venda()."""
    return {"produto": produto, "quantidade": quantidade, "preco": Decimal(preco)}


def hoje_str():
    return timezone.localdate().strftime("%Y-%m-%d")


def dados_venda(cliente, linhas, data=None, iniciais=0, pagamentos=None):
    """
    Monta o POST do formulário de venda (cabeçalho + formsets 'itens' e 'pgtos').
    Cada linha: {"produto": Produto|None, "quantidade": n, "preco": "x.xx", "item_id": id|None}.
    `pagamentos`: lista de {"metodo", "valor", "data", "pago"}; sem ela, a venda é paga
    de uma vez (1 pagamento Pix, já pago, no valor da soma das linhas).
    """
    dados = {
        "cliente": cliente.pk,
        "data_venda": data or agora_str(),
        "itens-TOTAL_FORMS": len(linhas),
        "itens-INITIAL_FORMS": iniciais,
        "itens-MIN_NUM_FORMS": 0,
        "itens-MAX_NUM_FORMS": 1000,
    }
    for i, linha in enumerate(linhas):
        produto = linha.get("produto")
        dados[f"itens-{i}-item_id"] = linha.get("item_id") or ""
        dados[f"itens-{i}-produto"] = produto.pk if produto else ""
        dados[f"itens-{i}-quantidade"] = linha["quantidade"]
        dados[f"itens-{i}-preco_venda_praticado"] = linha["preco"]

    if pagamentos is None:
        total = Decimal("0.00")
        for linha in linhas:
            try:
                total += Decimal(str(linha["quantidade"])) * Decimal(str(linha["preco"]))
            except Exception:  # linha vazia/inválida: o teste verifica o erro dos itens
                pass
        pagamentos = [{"metodo": "pix", "valor": total, "data": hoje_str(), "pago": True}]
    dados.update(
        {
            "pgtos-TOTAL_FORMS": len(pagamentos),
            "pgtos-INITIAL_FORMS": 0,
            "pgtos-MIN_NUM_FORMS": 0,
            "pgtos-MAX_NUM_FORMS": 1000,
        }
    )
    for i, p in enumerate(pagamentos):
        dados[f"pgtos-{i}-metodo"] = p.get("metodo", "pix")
        dados[f"pgtos-{i}-valor"] = p["valor"]
        dados[f"pgtos-{i}-data"] = p.get("data", hoje_str())
        if p.get("pago"):
            dados[f"pgtos-{i}-pago"] = "on"
    return dados


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
            itens=[item(self.produto_ana, 1, "2.00")],
        )
        for nome in ("gestao:venda_update", "gestao:venda_delete"):
            self.assertEqual(self.client.get(reverse(nome, args=[venda.pk])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("gestao:venda_delete", args=[venda.pk])).status_code, 404
        )
        self.assertTrue(Venda.objects.filter(pk=venda.pk).exists())

    def test_reverter_item_de_outro_usuario_retorna_404(self):
        venda = registrar_venda(
            usuario=self.ana,
            cliente=self.cliente_ana,
            itens=[item(self.produto_ana, 1, "2.00")],
        )
        item_ana = venda.itens.get()
        url = reverse("gestao:item_venda_delete", args=[item_ana.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(ItemVenda.objects.filter(pk=item_ana.pk).exists())

    def test_nao_edita_item_de_venda_de_outro_enviando_o_id(self):
        """Bia tenta editar a PRÓPRIA venda mas injeta o item_id de um item da Ana."""
        venda_ana = registrar_venda(
            usuario=self.ana,
            cliente=self.cliente_ana,
            itens=[item(self.produto_ana, 1, "2.00")],
        )
        item_ana = venda_ana.itens.get()
        cliente_bia = Cliente.objects.create(usuario=self.bia, nome="Cliente da Bia")
        produto_bia = Produto.objects.create(
            usuario=self.bia, nome="Item da Bia", quantidade=5,
            preco_compra=Decimal("1.00"), preco_venda=Decimal("2.00"),
        )
        venda_bia = registrar_venda(
            usuario=self.bia, cliente=cliente_bia, itens=[item(produto_bia, 1, "2.00")]
        )
        item_bia = venda_bia.itens.get()
        resp = self.client.post(
            reverse("gestao:venda_update", args=[venda_bia.pk]),
            dados_venda(
                cliente_bia,
                [
                    {"item_id": item_bia.pk, "quantidade": 1, "preco": "2.00"},
                    {"item_id": item_ana.pk, "quantidade": 5, "preco": "99.00"},
                ],
                iniciais=2,
            ),
        )
        self.assertEqual(resp.status_code, 403)  # PermissionDenied
        item_ana.refresh_from_db()
        self.assertEqual(item_ana.quantidade, 1)
        self.assertEqual(item_ana.preco_venda_praticado, Decimal("2.00"))

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
        # Cliente dela + item da Ana
        resp = self.client.post(
            reverse("gestao:venda_create"),
            dados_venda(cliente_bia, [{"produto": self.produto_ana, "quantidade": 1, "preco": "2.00"}]),
        )
        self.assertEqual(resp.status_code, 200)
        # Cliente da Ana + item dela mesma (nenhum dos dois é da Ana)
        resp = self.client.post(
            reverse("gestao:venda_create"),
            dados_venda(self.cliente_ana, [{"produto": self.produto_ana, "quantidade": 1, "preco": "2.00"}]),
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
        self.caneta = Produto.objects.create(
            usuario=self.user, nome="Caneta", quantidade=10,
            preco_compra=Decimal("2.00"), preco_venda=Decimal("5.00"),
        )
        self.lapis = Produto.objects.create(
            usuario=self.user, nome="Lápis", quantidade=20,
            preco_compra=Decimal("1.00"), preco_venda=Decimal("3.00"),
        )
        self.client.login(username="ana", password=SENHA)
        self.url = reverse("gestao:venda_create")

    def _post(self, linhas, data=None):
        return self.client.post(self.url, dados_venda(self.cliente, linhas, data=data))

    def test_tela_de_nova_venda_abre(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Nova venda")
        self.assertContains(resp, "Adicionar item")

    def test_venda_com_um_item_debita_estoque_e_calcula_lucro(self):
        resp = self._post([{"produto": self.caneta, "quantidade": 3, "preco": "6.00"}])
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        self.caneta.refresh_from_db()
        self.assertEqual(self.caneta.quantidade, 7)
        venda = Venda.objects.get()
        self.assertEqual(venda.usuario, self.user)
        self.assertEqual(venda.total, Decimal("18.00"))
        self.assertEqual(venda.lucro, Decimal("12.00"))  # (6 - 2) * 3

    def test_venda_com_varios_itens_soma_totais_e_debita_cada_estoque(self):
        resp = self._post(
            [
                {"produto": self.caneta, "quantidade": 3, "preco": "6.00"},  # 18 / lucro 12
                {"produto": self.lapis, "quantidade": 5, "preco": "4.00"},   # 20 / lucro 15
            ]
        )
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        self.caneta.refresh_from_db()
        self.lapis.refresh_from_db()
        self.assertEqual(self.caneta.quantidade, 7)
        self.assertEqual(self.lapis.quantidade, 15)

        venda = Venda.objects.get()
        self.assertEqual(venda.itens.count(), 2)
        self.assertEqual(venda.total, Decimal("38.00"))
        self.assertEqual(venda.lucro, Decimal("27.00"))
        # preço individual por item
        precos = {i.produto.nome: i.preco_venda_praticado for i in venda.itens.all()}
        self.assertEqual(precos, {"Caneta": Decimal("6.00"), "Lápis": Decimal("4.00")})

    def test_lucro_historico_nao_muda_se_custo_mudar_depois(self):
        self._post([{"produto": self.caneta, "quantidade": 1, "preco": "6.00"}])
        Produto.objects.filter(pk=self.caneta.pk).update(preco_compra=Decimal("5.00"))
        venda = Venda.objects.get()
        venda.recalcular_totais()
        self.assertEqual(venda.lucro, Decimal("4.00"))

    def test_estoque_insuficiente_em_um_item_desfaz_a_venda_toda(self):
        resp = self._post(
            [
                {"produto": self.caneta, "quantidade": 3, "preco": "6.00"},
                {"produto": self.lapis, "quantidade": 21, "preco": "4.00"},  # só há 20
            ]
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Estoque insuficiente")
        self.caneta.refresh_from_db()
        self.lapis.refresh_from_db()
        self.assertEqual(self.caneta.quantidade, 10)  # o 1º item NÃO ficou debitado
        self.assertEqual(self.lapis.quantidade, 20)
        self.assertEqual(Venda.objects.count(), 0)
        self.assertEqual(ItemVenda.objects.count(), 0)

    def test_mesmo_item_em_duas_linhas_e_rejeitado(self):
        resp = self._post(
            [
                {"produto": self.caneta, "quantidade": 1, "preco": "6.00"},
                {"produto": self.caneta, "quantidade": 2, "preco": "6.00"},
            ]
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "mais de uma vez")
        self.assertEqual(Venda.objects.count(), 0)
        self.caneta.refresh_from_db()
        self.assertEqual(self.caneta.quantidade, 10)

    def test_venda_sem_itens_e_rejeitada(self):
        resp = self._post([])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "pelo menos um item")
        self.assertEqual(Venda.objects.count(), 0)

    def test_linha_extra_em_branco_e_ignorada(self):
        resp = self._post(
            [
                {"produto": self.caneta, "quantidade": 1, "preco": "6.00"},
                {"produto": None, "quantidade": "", "preco": ""},
            ]
        )
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        self.assertEqual(Venda.objects.get().itens.count(), 1)

    def test_linha_sem_item_selecionado_e_rejeitada(self):
        resp = self._post([{"produto": None, "quantidade": 2, "preco": "6.00"}])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Selecione o item")
        self.assertEqual(Venda.objects.count(), 0)

    def test_venda_retroativa_grava_a_data_informada(self):
        resp = self._post(
            [{"produto": self.caneta, "quantidade": 1, "preco": "6.00"}],
            data="2026-01-10 14:30",
        )
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        esperado = timezone.make_aware(datetime(2026, 1, 10, 14, 30))
        self.assertEqual(Venda.objects.get().data_venda, esperado)

    def test_data_futura_e_rejeitada(self):
        amanha = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        resp = self._post(
            [{"produto": self.caneta, "quantidade": 1, "preco": "6.00"}], data=amanha
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "não pode ser no futuro")
        self.assertEqual(Venda.objects.count(), 0)

    def test_filtro_de_cliente_invalido_nao_quebra_a_listagem(self):
        resp = self.client.get(reverse("gestao:venda_list"), {"cliente": "abc"})
        self.assertEqual(resp.status_code, 200)

    def test_filtro_por_cliente(self):
        outro = Cliente.objects.create(usuario=self.user, nome="Loja Y")
        self._post([{"produto": self.caneta, "quantidade": 1, "preco": "6.00"}])
        registrar_venda(usuario=self.user, cliente=outro, itens=[item(self.caneta, 1, "5.00")])
        resp = self.client.get(reverse("gestao:venda_list"), {"cliente": outro.pk})
        self.assertEqual(len(resp.context["object_list"]), 1)
        self.assertEqual(resp.context["object_list"][0].cliente, outro)

    def test_listagem_mostra_os_itens_da_venda(self):
        self._post(
            [
                {"produto": self.caneta, "quantidade": 3, "preco": "6.00"},
                {"produto": self.lapis, "quantidade": 5, "preco": "4.00"},
            ]
        )
        resp = self.client.get(reverse("gestao:venda_list"))
        self.assertContains(resp, "Caneta")
        self.assertContains(resp, "Lápis")
        self.assertContains(resp, "Reverter item")  # 2 itens -> reversão individual

    def test_item_com_vendas_nao_pode_ser_excluido_do_estoque(self):
        self._post([{"produto": self.caneta, "quantidade": 1, "preco": "6.00"}])
        resp = self.client.post(reverse("gestao:produto_delete", args=[self.caneta.pk]))
        self.assertRedirects(resp, reverse("gestao:produto_list"))
        self.assertTrue(Produto.objects.filter(pk=self.caneta.pk).exists())


# ==========================================================================
# Editar venda (produto e custo travados, estoque ajustado, itens novos)
# ==========================================================================
@sem_axes
class VendaEdicaoTests(TestCase):
    DATA_ORIGINAL = datetime(2026, 1, 10, 15, 30, 45)  # com segundos, de propósito

    def setUp(self):
        self.user = criar_usuario("ana")
        self.cliente = Cliente.objects.create(usuario=self.user, nome="Loja X")
        self.caneta = Produto.objects.create(
            usuario=self.user, nome="Caneta", quantidade=10,
            preco_compra=Decimal("2.00"), preco_venda=Decimal("5.00"),
        )
        self.lapis = Produto.objects.create(
            usuario=self.user, nome="Lápis", quantidade=20,
            preco_compra=Decimal("1.00"), preco_venda=Decimal("3.00"),
        )
        self.borracha = Produto.objects.create(
            usuario=self.user, nome="Borracha", quantidade=8,
            preco_compra=Decimal("1.50"), preco_venda=Decimal("2.50"),
        )
        self.client.login(username="ana", password=SENHA)
        # Vende 3 canetas (@6) e 2 lápis (@4): estoque Caneta 7, Lápis 18
        self.venda = registrar_venda(
            usuario=self.user,
            cliente=self.cliente,
            itens=[item(self.caneta, 3, "6.00"), item(self.lapis, 2, "4.00")],
            data_venda=timezone.make_aware(self.DATA_ORIGINAL),
        )
        self.item_caneta = self.venda.itens.get(produto=self.caneta)
        self.item_lapis = self.venda.itens.get(produto=self.lapis)
        self.url = reverse("gestao:venda_update", args=[self.venda.pk])

    def _editar(self, caneta=(3, "6.00"), lapis=(2, "4.00"), novos=(), data="2026-01-10 15:30"):
        """caneta/lapis = (quantidade, preço) das linhas existentes; novos = linhas novas."""
        # A ordem das linhas existentes segue a do banco (por id): caneta, lapis.
        linhas = [
            {"item_id": self.item_caneta.pk, "quantidade": caneta[0], "preco": caneta[1]},
            {"item_id": self.item_lapis.pk, "quantidade": lapis[0], "preco": lapis[1]},
        ] + list(novos)
        return self.client.post(
            self.url, dados_venda(self.cliente, linhas, data=data, iniciais=2)
        )

    def _estoque(self, produto):
        produto.refresh_from_db()
        return produto.quantidade

    def test_tela_de_edicao_mostra_data_e_itens(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Editar venda")
        self.assertContains(resp, 'value="2026-01-10 15:30"')
        self.assertContains(resp, "Caneta")
        self.assertContains(resp, "Lápis")

    def test_aumentar_quantidade_debita_a_diferenca_do_estoque(self):
        resp = self._editar(caneta=(5, "6.00"))
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        self.assertEqual(self._estoque(self.caneta), 5)  # 7 - 2
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.total, Decimal("38.00"))  # 30 + 8
        self.assertEqual(self.venda.lucro, Decimal("26.00"))  # 20 + 6

    def test_diminuir_quantidade_devolve_ao_estoque(self):
        self._editar(lapis=(1, "4.00"))
        self.assertEqual(self._estoque(self.lapis), 19)  # 18 + 1
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.total, Decimal("22.00"))  # 18 + 4

    def test_pode_usar_exatamente_todo_o_estoque_disponivel(self):
        self._editar(caneta=(10, "6.00"))  # 7 em estoque + 3 que o item já usa
        self.assertEqual(self._estoque(self.caneta), 0)

    def test_acima_do_disponivel_e_rejeitado_sem_mexer_em_nada(self):
        resp = self._editar(lapis=(3, "4.00"), caneta=(11, "6.00"))  # caneta passa do limite
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Estoque insuficiente")
        # nada mudou, nem o lápis (que seria válido sozinho)
        self.assertEqual(self._estoque(self.caneta), 7)
        self.assertEqual(self._estoque(self.lapis), 18)
        self.item_lapis.refresh_from_db()
        self.assertEqual(self.item_lapis.quantidade, 2)

    def test_adicionar_item_novo_a_venda(self):
        resp = self._editar(
            novos=[{"produto": self.borracha, "quantidade": 4, "preco": "3.00"}]
        )
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        self.assertEqual(self.venda.itens.count(), 3)
        self.assertEqual(self._estoque(self.borracha), 4)
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.total, Decimal("38.00"))   # 18 + 8 + 12
        self.assertEqual(self.venda.lucro, Decimal("24.00"))   # 12 + 6 + 6

    def test_adicionar_item_que_ja_esta_na_venda_e_rejeitado(self):
        resp = self._editar(
            novos=[{"produto": self.caneta, "quantidade": 1, "preco": "6.00"}]
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "já está nesta venda")
        self.assertEqual(self.venda.itens.count(), 2)
        self.assertEqual(self._estoque(self.caneta), 7)

    def test_produto_de_item_existente_nao_pode_ser_trocado(self):
        linhas = [
            # tenta trocar a caneta por borracha enviando outro produto
            {"item_id": self.item_caneta.pk, "produto": self.borracha, "quantidade": 3, "preco": "6.00"},
            {"item_id": self.item_lapis.pk, "quantidade": 2, "preco": "4.00"},
        ]
        self.client.post(
            self.url, dados_venda(self.cliente, linhas, data="2026-01-10 15:30", iniciais=2)
        )
        self.item_caneta.refresh_from_db()
        self.assertEqual(self.item_caneta.produto, self.caneta)
        self.assertEqual(self._estoque(self.borracha), 8)

    def test_edicao_nao_remove_itens_que_ficaram_de_fora_do_envio(self):
        # envia só a linha da caneta; o lápis continua na venda
        self.client.post(
            self.url,
            dados_venda(
                self.cliente,
                [{"item_id": self.item_caneta.pk, "quantidade": 3, "preco": "6.00"}],
                data="2026-01-10 15:30",
                iniciais=1,
            ),
        )
        self.assertEqual(self.venda.itens.count(), 2)

    def test_data_original_e_mantida_com_segundos_quando_nao_alterada(self):
        self._editar(data="2026-01-10 15:30")  # mesmo minuto da original
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.data_venda, timezone.make_aware(self.DATA_ORIGINAL))

    def test_data_pode_ser_alterada(self):
        self._editar(data="2026-01-11 10:00")
        self.venda.refresh_from_db()
        self.assertEqual(
            self.venda.data_venda, timezone.make_aware(datetime(2026, 1, 11, 10, 0))
        )

    def test_custo_historico_e_preservado_ao_editar(self):
        Produto.objects.filter(pk=self.caneta.pk).update(preco_compra=Decimal("5.00"))
        self._editar(caneta=(3, "7.00"))
        self.item_caneta.refresh_from_db()
        self.assertEqual(self.item_caneta.preco_compra_unitario, Decimal("2.00"))
        self.assertEqual(self.item_caneta.lucro, Decimal("15.00"))  # (7 - 2) * 3


# ==========================================================================
# Reverter (estornar) venda inteira ou um item
# ==========================================================================
@sem_axes
class VendaReversaoTests(TestCase):
    def setUp(self):
        self.user = criar_usuario("ana")
        self.cliente = Cliente.objects.create(usuario=self.user, nome="Loja X")
        self.caneta = Produto.objects.create(
            usuario=self.user, nome="Caneta", quantidade=10,
            preco_compra=Decimal("2.00"), preco_venda=Decimal("5.00"),
        )
        self.lapis = Produto.objects.create(
            usuario=self.user, nome="Lápis", quantidade=20,
            preco_compra=Decimal("1.00"), preco_venda=Decimal("3.00"),
        )
        self.client.login(username="ana", password=SENHA)
        self.venda = registrar_venda(
            usuario=self.user,
            cliente=self.cliente,
            itens=[item(self.caneta, 4, "5.00"), item(self.lapis, 6, "3.00")],
        )

    def _qtd(self, produto):
        produto.refresh_from_db()
        return produto.quantidade

    def test_reverter_venda_devolve_todos_os_itens_ao_estoque(self):
        self.assertEqual(self._qtd(self.caneta), 6)
        self.assertEqual(self._qtd(self.lapis), 14)
        resp = self.client.post(reverse("gestao:venda_delete", args=[self.venda.pk]))
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        self.assertEqual(self._qtd(self.caneta), 10)
        self.assertEqual(self._qtd(self.lapis), 20)
        self.assertFalse(Venda.objects.filter(pk=self.venda.pk).exists())
        self.assertEqual(ItemVenda.objects.count(), 0)

    def test_tela_de_confirmacao_nao_altera_nada(self):
        resp = self.client.get(reverse("gestao:venda_delete", args=[self.venda.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Caneta")
        self.assertTrue(Venda.objects.filter(pk=self.venda.pk).exists())

    def test_reverter_um_item_devolve_so_ele_e_recalcula_a_venda(self):
        item_caneta = self.venda.itens.get(produto=self.caneta)
        url = reverse("gestao:item_venda_delete", args=[item_caneta.pk])
        self.assertEqual(self.client.get(url).status_code, 200)  # confirmação não altera

        resp = self.client.post(url)
        # o total mudou e os pagamentos já não fecham: vai direto para a edição
        self.assertRedirects(resp, reverse("gestao:venda_update", args=[self.venda.pk]))
        self.assertEqual(self._qtd(self.caneta), 10)  # voltou
        self.assertEqual(self._qtd(self.lapis), 14)   # intacto
        self.venda.refresh_from_db()
        self.assertEqual(self.venda.itens.count(), 1)
        self.assertEqual(self.venda.total, Decimal("18.00"))  # só o lápis: 6 * 3
        self.assertEqual(self.venda.lucro, Decimal("12.00"))  # (3 - 1) * 6

    def test_reverter_o_ultimo_item_reverte_a_venda_inteira(self):
        for it in list(self.venda.itens.all()):
            self.client.post(reverse("gestao:item_venda_delete", args=[it.pk]))
        self.assertFalse(Venda.objects.filter(pk=self.venda.pk).exists())
        self.assertEqual(self._qtd(self.caneta), 10)
        self.assertEqual(self._qtd(self.lapis), 20)

    def test_venda_de_um_item_pode_ser_revertida_por_completo(self):
        unica = registrar_venda(
            usuario=self.user, cliente=self.cliente, itens=[item(self.caneta, 1, "5.00")]
        )
        it = unica.itens.get()
        self.client.post(reverse("gestao:item_venda_delete", args=[it.pk]))
        self.assertFalse(Venda.objects.filter(pk=unica.pk).exists())
        self.assertEqual(self._qtd(self.caneta), 6)  # 10 - 4 (venda 1) = 6; a 1 unidade da venda única voltou


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
            usuario=self.user, nome="Item", quantidade=50,
            preco_compra=Decimal("10.00"), preco_venda=Decimal("15.00"),
        )
        self.client.login(username="ana", password=SENHA)
        self.url = reverse("gestao:dashboard")

    def _vender(self, cliente, qtd, preco, data=None):
        return registrar_venda(
            usuario=self.user, cliente=cliente,
            itens=[item(self.produto, qtd, preco)], data_venda=data,
        )

    def _em(self, ano, mes, dia=15):
        return timezone.make_aware(datetime(ano, mes, dia, 12, 0))

    def test_metricas_do_mes_atual(self):
        self._vender(self.c1, 2, "15.00")  # total 30, lucro 10
        self._vender(self.c1, 1, "12.00")  # total 12, lucro 2
        self._vender(self.c2, 1, "20.00")  # total 20, lucro 10
        Prospeccao.objects.create(
            usuario=self.user, cliente=self.c1, descricao="Ligar",
            data_contato=timezone.localdate(),
        )
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["total_vendas"], Decimal("62.00"))
        self.assertEqual(ctx["total_lucro"], Decimal("22.00"))
        self.assertEqual(ctx["qtd_prospeccoes"], 1)
        self.assertEqual(ctx["total_clientes"], 2)
        self.assertEqual(ctx["clientes_compradores"], 2)

    def test_venda_com_varios_itens_conta_uma_vez_no_total(self):
        outro = Produto.objects.create(
            usuario=self.user, nome="Outro", quantidade=10,
            preco_compra=Decimal("1.00"), preco_venda=Decimal("2.00"),
        )
        registrar_venda(
            usuario=self.user, cliente=self.c1,
            itens=[item(self.produto, 1, "15.00"), item(outro, 2, "3.00")],
        )
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["total_vendas"], Decimal("21.00"))
        self.assertEqual(ctx["total_lucro"], Decimal("9.00"))  # 5 + 4
        self.assertEqual(ctx["clientes_compradores"], 1)

    def test_dashboard_vazio_mostra_zeros(self):
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["total_vendas"], Decimal("0.00"))
        self.assertEqual(ctx["clientes_compradores"], 0)

    def test_reverter_venda_atualiza_as_metricas(self):
        venda = self._vender(self.c1, 2, "15.00")
        self.client.post(reverse("gestao:venda_delete", args=[venda.pk]))
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["total_vendas"], Decimal("0.00"))

    def test_valor_do_estoque_usa_o_custo_de_aquisicao(self):
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["valor_estoque"], Decimal("500.00"))  # 50 * 10
        self._vender(self.c1, 2, "15.00")
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["valor_estoque"], Decimal("480.00"))  # 48 * 10

    def test_filtros_de_ano_e_mes_so_listam_periodos_com_venda(self):
        self._vender(self.c1, 1, "15.00", data=self._em(2024, 3))
        self._vender(self.c1, 1, "20.00", data=self._em(2024, 8))
        self._vender(self.c2, 2, "30.00", data=self._em(2025, 5))

        # Sem filtro: abre no mês mais recente com venda (maio/2025)
        ctx = self.client.get(self.url).context
        self.assertEqual(ctx["anos"], [2025, 2024])
        self.assertEqual(ctx["ano_selecionado"], 2025)
        self.assertEqual(ctx["mes_selecionado"], 5)
        self.assertEqual(ctx["total_vendas"], Decimal("60.00"))

        # 2024 inteiro: só os meses com venda (agosto e março)
        ctx = self.client.get(self.url, {"ano": "2024", "mes": "todos"}).context
        self.assertEqual([m.month for m in ctx["meses"]], [8, 3])
        self.assertIsNone(ctx["mes_selecionado"])
        self.assertEqual(ctx["total_vendas"], Decimal("35.00"))

        # um mês específico
        ctx = self.client.get(self.url, {"ano": "2024", "mes": "3"}).context
        self.assertEqual(ctx["total_vendas"], Decimal("15.00"))

        # todos os anos = tudo
        ctx = self.client.get(self.url, {"ano": "todos"}).context
        self.assertIsNone(ctx["ano_selecionado"])
        self.assertEqual(ctx["meses"], [])
        self.assertEqual(ctx["total_vendas"], Decimal("95.00"))

    def test_filtros_invalidos_viram_todos(self):
        self._vender(self.c1, 1, "15.00", data=self._em(2024, 3))
        ctx = self.client.get(self.url, {"ano": "2.024", "mes": "3"}).context
        self.assertIsNone(ctx["ano_selecionado"])
        ctx = self.client.get(self.url, {"ano": "1999"}).context
        self.assertIsNone(ctx["ano_selecionado"])
        ctx = self.client.get(self.url, {"ano": "2024", "mes": "12"}).context  # mês sem venda
        self.assertIsNone(ctx["mes_selecionado"])
        self.assertEqual(ctx["total_vendas"], Decimal("15.00"))

    def test_ano_aparece_sem_separador_de_milhar(self):
        self._vender(self.c1, 1, "15.00", data=self._em(2024, 3))
        resp = self.client.get(self.url)
        self.assertContains(resp, ">2024</option>")
        self.assertNotContains(resp, "2.024")


# ==========================================================================
# Limites numéricos e edição segura do estoque
# ==========================================================================
@sem_axes
class LimitesTests(TestCase):
    def setUp(self):
        self.user = criar_usuario("ana")
        self.cliente = Cliente.objects.create(usuario=self.user, nome="Loja X")
        self.client.login(username="ana", password=SENHA)

    def _produto(self, nome="Item", qtd=10, custo="2.00", venda="5.00"):
        return Produto.objects.create(
            usuario=self.user, nome=nome, quantidade=qtd,
            preco_compra=Decimal(custo), preco_venda=Decimal(venda),
        )

    def test_estoque_recusa_quantidade_e_precos_acima_do_limite(self):
        url = reverse("gestao:produto_create")
        resp = self.client.post(
            url,
            {"nome": "Caro", "quantidade": 1_000_001, "preco_compra": "1.00", "preco_venda": "1.00"},
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            url,
            {"nome": "Caro", "quantidade": 1, "preco_compra": "1000000.00", "preco_venda": "1.00"},
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            url,
            {"nome": "Caro", "quantidade": 1, "preco_compra": "1.00", "preco_venda": "1000000.00"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Produto.objects.count(), 0)

    def test_estoque_aceita_exatamente_o_limite(self):
        resp = self.client.post(
            reverse("gestao:produto_create"),
            {"nome": "Limite", "quantidade": 1_000_000, "preco_compra": "999999.99", "preco_venda": "999999.99"},
        )
        self.assertRedirects(resp, reverse("gestao:produto_list"))
        self.assertEqual(Produto.objects.get().quantidade, 1_000_000)

    def test_venda_recusa_quantidade_e_preco_acima_do_limite(self):
        p = self._produto(qtd=1_000_000)
        url = reverse("gestao:venda_create")
        resp = self.client.post(
            url, dados_venda(self.cliente, [{"produto": p, "quantidade": 1_000_001, "preco": "1.00"}])
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            url, dados_venda(self.cliente, [{"produto": p, "quantidade": 1, "preco": "1000000.00"}])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Venda.objects.count(), 0)

    def test_um_item_no_limite_maximo_e_aceito(self):
        p = self._produto(qtd=1_000_000, custo="0.00", venda="999999.99")
        resp = self.client.post(
            reverse("gestao:venda_create"),
            dados_venda(self.cliente, [{"produto": p, "quantidade": 1_000_000, "preco": "999999.99"}]),
        )
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        self.assertEqual(Venda.objects.get().total, Decimal("999999990000.00"))

    def test_soma_dos_itens_acima_do_limite_desfaz_a_venda(self):
        a = self._produto("A", qtd=1_000_000, custo="0.00", venda="999999.99")
        b = self._produto("B", qtd=1_000_000, custo="0.00", venda="999999.99")
        resp = self.client.post(
            reverse("gestao:venda_create"),
            dados_venda(
                self.cliente,
                [
                    {"produto": a, "quantidade": 1_000_000, "preco": "999999.99"},
                    {"produto": b, "quantidade": 1_000_000, "preco": "999999.99"},
                ],
            ),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "grande demais")
        self.assertEqual(Venda.objects.count(), 0)
        self.assertEqual(ItemVenda.objects.count(), 0)
        a.refresh_from_db()
        self.assertEqual(a.quantidade, 1_000_000)  # estoque não foi debitado

    def test_edicao_de_estoque_exibe_a_quantidade_original_oculta(self):
        p = self._produto()
        resp = self.client.get(reverse("gestao:produto_update", args=[p.pk]))
        self.assertContains(resp, 'name="quantidade_original"')
        self.assertContains(resp, 'value="10"')

    def test_edicao_barra_o_salvamento_se_o_estoque_mudou_no_meio(self):
        p = self._produto(qtd=10)
        url = reverse("gestao:produto_update", args=[p.pk])
        # Tela aberta com estoque 10; antes de salvar, uma venda tira 1 unidade.
        registrar_venda(usuario=self.user, cliente=self.cliente, itens=[item(p, 1, "5.00")])
        dados = {
            "nome": "Item", "quantidade": 10, "quantidade_original": 10,
            "preco_compra": "2.00", "preco_venda": "5.00",
        }
        resp = self.client.post(url, dados)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "mudou enquanto você editava")
        p.refresh_from_db()
        self.assertEqual(p.quantidade, 9)  # a venda NÃO foi sobrescrita

        # Reenviando com o estoque atualizado (9) o salvamento passa.
        dados.update({"quantidade": 20, "quantidade_original": 9})
        resp = self.client.post(url, dados)
        self.assertRedirects(resp, reverse("gestao:produto_list"))
        p.refresh_from_db()
        self.assertEqual(p.quantidade, 20)

    def test_edicao_sem_mudanca_no_meio_salva_normalmente(self):
        p = self._produto(qtd=10)
        resp = self.client.post(
            reverse("gestao:produto_update", args=[p.pk]),
            {"nome": "Novo nome", "quantidade": 7, "quantidade_original": 10,
             "preco_compra": "2.00", "preco_venda": "5.00"},
        )
        self.assertRedirects(resp, reverse("gestao:produto_list"))
        p.refresh_from_db()
        self.assertEqual((p.nome, p.quantidade), ("Novo nome", 7))

    def test_novo_item_nao_tem_o_campo_de_quantidade_original(self):
        resp = self.client.get(reverse("gestao:produto_create"))
        self.assertNotContains(resp, "quantidade_original")


# ==========================================================================
# Pagamentos
# ==========================================================================
@sem_axes
class PagamentoTests(TestCase):
    def setUp(self):
        self.user = criar_usuario("ana")
        self.cliente = Cliente.objects.create(usuario=self.user, nome="Loja X")
        self.caneta = Produto.objects.create(
            usuario=self.user, nome="Caneta", quantidade=50,
            preco_compra=Decimal("2.00"), preco_venda=Decimal("5.00"),
        )
        self.client.login(username="ana", password=SENHA)
        self.hoje = timezone.localdate()

    def _venda(self, qtd=10, preco="10.00", pagamentos=None):
        return registrar_venda(
            usuario=self.user, cliente=self.cliente,
            itens=[item(self.caneta, qtd, preco)], pagamentos=pagamentos,
        )

    def _pg(self, valor, dias=0, pago=False, metodo="pix"):
        return {
            "metodo": metodo, "valor": Decimal(valor),
            "data": self.hoje + timedelta(days=dias), "pago": pago,
        }

    # ---- serviço ----
    def test_sem_pagamentos_a_venda_nasce_quitada(self):
        v = self._venda()
        p = v.pagamentos.get()
        self.assertEqual((p.valor, p.pago), (Decimal("100.00"), True))
        self.assertEqual(v.pagamentos_resumo()["estado"], "quitado")

    def test_pagamentos_que_nao_fecham_sao_recusados_e_nada_e_gravado(self):
        with self.assertRaises(VendaInvalida):
            self._venda(pagamentos=[self._pg("60.00", pago=True), self._pg("30.00", 30)])
        self.assertEqual(Venda.objects.count(), 0)
        self.caneta.refresh_from_db()
        self.assertEqual(self.caneta.quantidade, 50)  # estoque intacto

    def test_pagamentos_que_passam_do_total_sao_recusados(self):
        with self.assertRaises(VendaInvalida):
            self._venda(pagamentos=[self._pg("100.01", pago=True)])

    def test_pagamento_parte_paga_parte_pendente(self):
        v = self._venda(pagamentos=[self._pg("40.00", pago=True), self._pg("60.00", 30)])
        r = v.pagamentos_resumo()
        self.assertEqual((r["estado"], r["pago"], r["pendente"]), ("pendente", Decimal("40.00"), Decimal("60.00")))

    def test_pendente_vencido_vira_atrasado(self):
        v = self._venda(pagamentos=[self._pg("100.00", -3)])
        self.assertEqual(v.pagamentos_resumo()["estado"], "atrasado")

    # ---- formulário ----
    def test_nova_venda_parcelada_pelo_formulario(self):
        pg = [
            {"metodo": "pix", "valor": "40.00", "data": hoje_str(), "pago": True},
            {"metodo": "credito", "valor": "30.00", "data": (self.hoje + timedelta(days=30)).isoformat()},
            {"metodo": "credito", "valor": "30.00", "data": (self.hoje + timedelta(days=60)).isoformat()},
        ]
        resp = self.client.post(
            reverse("gestao:venda_create"),
            dados_venda(self.cliente, [{"produto": self.caneta, "quantidade": 10, "preco": "10.00"}], pagamentos=pg),
        )
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        v = Venda.objects.get()
        self.assertEqual(v.pagamentos.count(), 3)
        self.assertEqual(v.pagamentos.filter(pago=True).count(), 1)

    def test_formulario_recusa_pagamentos_que_nao_fecham(self):
        pg = [{"metodo": "pix", "valor": "50.00", "data": hoje_str(), "pago": True}]
        resp = self.client.post(
            reverse("gestao:venda_create"),
            dados_venda(self.cliente, [{"produto": self.caneta, "quantidade": 10, "preco": "10.00"}], pagamentos=pg),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Os pagamentos somam")
        self.assertEqual(Venda.objects.count(), 0)
        self.caneta.refresh_from_db()
        self.assertEqual(self.caneta.quantidade, 50)

    def test_pagamento_pago_com_data_futura_e_recusado(self):
        pg = [{"metodo": "pix", "valor": "100.00",
               "data": (self.hoje + timedelta(days=5)).isoformat(), "pago": True}]
        resp = self.client.post(
            reverse("gestao:venda_create"),
            dados_venda(self.cliente, [{"produto": self.caneta, "quantidade": 10, "preco": "10.00"}], pagamentos=pg),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Venda.objects.count(), 0)

    # ---- edição ----
    def test_editar_itens_exige_ajustar_os_pagamentos(self):
        v = self._venda(pagamentos=[self._pg("100.00", pago=True)])
        it = v.itens.get()
        linhas = [{"item_id": it.pk, "quantidade": 5, "preco": "10.00"}]  # total passa a 50
        # pagamentos antigos (100) não fecham
        resp = self.client.post(
            reverse("gestao:venda_update", args=[v.pk]),
            dados_venda(self.cliente, linhas, iniciais=1,
                        pagamentos=[{"metodo": "pix", "valor": "100.00", "data": hoje_str(), "pago": True}]),
        )
        self.assertEqual(resp.status_code, 200)
        it.refresh_from_db()
        self.assertEqual(it.quantidade, 10)  # nada mudou
        # ajustando, salva
        resp = self.client.post(
            reverse("gestao:venda_update", args=[v.pk]),
            dados_venda(self.cliente, linhas, iniciais=1,
                        pagamentos=[{"metodo": "pix", "valor": "50.00", "data": hoje_str(), "pago": True}]),
        )
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        v.refresh_from_db()
        self.assertEqual(v.total, Decimal("50.00"))
        self.assertEqual(v.pagamentos.get().valor, Decimal("50.00"))

    def test_tela_de_edicao_mostra_pagamentos_existentes(self):
        v = self._venda(pagamentos=[self._pg("40.00", pago=True), self._pg("60.00", 30)])
        resp = self.client.get(reverse("gestao:venda_update", args=[v.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="pgtos-1-valor"')
        self.assertContains(resp, 'value="60.00"')

    def test_linha_de_pagamento_removida_no_navegador_nao_gera_erro(self):
        v = self._venda(pagamentos=[self._pg("40.00", pago=True), self._pg("60.00", 30)])
        it = v.itens.get()
        dados = dados_venda(self.cliente, [{"item_id": it.pk, "quantidade": 10, "preco": "10.00"}], iniciais=1,
                            pagamentos=[{"metodo": "pix", "valor": "100.00", "data": hoje_str(), "pago": True}])
        # simula o navegador: TOTAL_FORMS=3, mas só o índice 2 foi enviado (0 e 1 removidos)
        for k in ("metodo", "valor", "data", "pago"):
            if f"pgtos-0-{k}" in dados:
                dados[f"pgtos-2-{k}"] = dados.pop(f"pgtos-0-{k}")
        dados["pgtos-TOTAL_FORMS"] = 3
        resp = self.client.post(reverse("gestao:venda_update", args=[v.pk]), dados)
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        self.assertEqual(v.pagamentos.count(), 1)

    def test_erro_nao_recria_linha_em_branco_de_pagamento_removida(self):
        # Navegador: TOTAL_FORMS=3, mas só o índice 2 foi enviado (0 e 1 removidos) e a soma não fecha
        dados = dados_venda(
            self.cliente,
            [{"produto": self.caneta, "quantidade": 10, "preco": "10.00"}],
            pagamentos=[{"metodo": "pix", "valor": "50.00", "data": hoje_str(), "pago": True}],
        )
        for k in ("metodo", "valor", "data", "pago"):
            if f"pgtos-0-{k}" in dados:
                dados[f"pgtos-2-{k}"] = dados.pop(f"pgtos-0-{k}")
        dados["pgtos-TOTAL_FORMS"] = 3
        resp = self.client.post(reverse("gestao:venda_create"), dados)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Os pagamentos somam")
        self.assertContains(resp, 'name="pgtos-2-valor"')
        self.assertNotContains(resp, 'name="pgtos-0-valor"')
        self.assertNotContains(resp, 'name="pgtos-1-valor"')

    # ---- reversão ----
    def test_reverter_um_item_com_pagamento_fechado_pede_ajuste(self):
        outro = Produto.objects.create(
            usuario=self.user, nome="Lápis", quantidade=20,
            preco_compra=Decimal("1.00"), preco_venda=Decimal("3.00"),
        )
        v = registrar_venda(
            usuario=self.user, cliente=self.cliente,
            itens=[item(self.caneta, 2, "10.00"), item(outro, 4, "5.00")],
        )
        self.assertEqual(v.total, Decimal("40.00"))
        it = v.itens.get(produto=outro)
        resp = self.client.post(reverse("gestao:item_venda_delete", args=[it.pk]))
        self.assertRedirects(resp, reverse("gestao:venda_update", args=[v.pk]))
        v = Venda.objects.get(pk=v.pk)
        self.assertEqual(v.pagamentos_resumo()["estado"], "ajustar")

    def test_reverter_venda_apaga_os_pagamentos(self):
        v = self._venda()
        self.client.post(reverse("gestao:venda_delete", args=[v.pk]))
        self.assertEqual(Pagamento.objects.count(), 0)

    # ---- confirmar / desfazer ----
    def test_confirmar_e_desfazer_pagamento(self):
        v = self._venda(pagamentos=[self._pg("100.00", 30)])
        p = v.pagamentos.get()
        resp = self.client.post(reverse("gestao:pagamento_confirmar", args=[p.pk]))
        self.assertRedirects(resp, reverse("gestao:venda_list"))
        p.refresh_from_db()
        self.assertTrue(p.pago)
        self.assertEqual(p.data, self.hoje)
        self.client.post(reverse("gestao:pagamento_desfazer", args=[p.pk]))
        p.refresh_from_db()
        self.assertFalse(p.pago)

    def test_confirmar_exige_post(self):
        v = self._venda(pagamentos=[self._pg("100.00", 30)])
        p = v.pagamentos.get()
        resp = self.client.get(reverse("gestao:pagamento_confirmar", args=[p.pk]))
        self.assertEqual(resp.status_code, 405)
        p.refresh_from_db()
        self.assertFalse(p.pago)

    def test_next_externo_e_ignorado(self):
        v = self._venda(pagamentos=[self._pg("100.00", 30)])
        p = v.pagamentos.get()
        resp = self.client.post(
            reverse("gestao:pagamento_confirmar", args=[p.pk]), {"next": "https://evil.example/"}
        )
        self.assertRedirects(resp, reverse("gestao:venda_list"))

    def test_nao_confirma_pagamento_de_outro_usuario(self):
        bia = criar_usuario("bia")
        cli = Cliente.objects.create(usuario=bia, nome="Cliente da Bia")
        prod = Produto.objects.create(
            usuario=bia, nome="X", quantidade=5,
            preco_compra=Decimal("1.00"), preco_venda=Decimal("2.00"),
        )
        vb = registrar_venda(
            usuario=bia, cliente=cli, itens=[item(prod, 1, "2.00")],
            pagamentos=[{"metodo": "pix", "valor": Decimal("2.00"), "data": self.hoje, "pago": False}],
        )
        p = vb.pagamentos.get()
        resp = self.client.post(reverse("gestao:pagamento_confirmar", args=[p.pk]))
        self.assertEqual(resp.status_code, 404)
        p.refresh_from_db()
        self.assertFalse(p.pago)

    # ---- lista / filtros ----
    def test_filtros_da_lista_de_vendas(self):
        quitada = self._venda(qtd=1)
        pendente = self._venda(qtd=2, pagamentos=[self._pg("20.00", 15)])
        atrasada = self._venda(qtd=3, pagamentos=[self._pg("10.00", pago=True), self._pg("20.00", -5)])
        ajustar = self._venda(qtd=4)
        ajustar.pagamentos.update(valor=Decimal("1.00"))
        url = reverse("gestao:venda_list")

        def ids(filtro):
            resp = self.client.get(url, {"pagamento": filtro})
            return {v.pk for v in resp.context["object_list"]}

        self.assertEqual(ids("quitado"), {quitada.pk})
        self.assertEqual(ids("pendente"), {pendente.pk, atrasada.pk})
        self.assertEqual(ids("atrasado"), {atrasada.pk})
        self.assertEqual(ids("ajustar"), {ajustar.pk})
        self.assertEqual(len(ids("")), 4)
        self.assertEqual(len(ids("lixo")), 4)  # valor inválido é ignorado

    def test_filtro_nao_mostra_vendas_de_outro_usuario(self):
        bia = criar_usuario("bia")
        cli = Cliente.objects.create(usuario=bia, nome="Cliente da Bia")
        prod = Produto.objects.create(
            usuario=bia, nome="X", quantidade=5,
            preco_compra=Decimal("1.00"), preco_venda=Decimal("2.00"),
        )
        registrar_venda(
            usuario=bia, cliente=cli, itens=[item(prod, 1, "2.00")],
            pagamentos=[{"metodo": "pix", "valor": Decimal("2.00"), "data": self.hoje, "pago": False}],
        )
        resp = self.client.get(reverse("gestao:venda_list"), {"pagamento": "pendente"})
        self.assertEqual(len(resp.context["object_list"]), 0)

    # ---- dashboard ----
    def test_dashboard_recebido_a_receber_e_atrasado(self):
        self._venda(pagamentos=[self._pg("30.00", pago=True), self._pg("50.00", 0), self._pg("20.00", -2)])
        resp = self.client.get(reverse("gestao:dashboard"), {"ano": "todos"})
        self.assertEqual(resp.context["recebido"], Decimal("30.00"))
        self.assertEqual(resp.context["a_receber"], Decimal("70.00"))
        self.assertEqual(resp.context["atrasado"], Decimal("20.00"))
        self.assertEqual(resp.context["total_vendas"], Decimal("100.00"))  # vendas/lucro como antes


@sem_axes
class OrdemDosItensNaVendaTests(TestCase):
    def test_itens_do_formulario_de_venda_em_ordem_alfabetica(self):
        user = criar_usuario("ana")
        for nome in ["banana", "Cebola", "abacate"]:
            Produto.objects.create(
                usuario=user, nome=nome, quantidade=1,
                preco_compra=Decimal("1.00"), preco_venda=Decimal("2.00"),
            )
        Produto.objects.create(  # sem estoque: não aparece
            usuario=user, nome="Aaa sem estoque", quantidade=0,
            preco_compra=Decimal("1.00"), preco_venda=Decimal("2.00"),
        )
        self.client.login(username="ana", password=SENHA)
        resp = self.client.get(reverse("gestao:venda_create"))
        nomes = [p.nome for p in resp.context["formset"].forms[0].fields["produto"].queryset]
        self.assertEqual(nomes, ["abacate", "banana", "Cebola"])


# ==========================================================================
# Histórico do cliente, PDF da venda e ordem dos clientes
# ==========================================================================
@sem_axes
class HistoricoPdfTests(TestCase):
    def setUp(self):
        self.user = criar_usuario("ana")
        self.cliente = Cliente.objects.create(usuario=self.user, nome="João da Silva")
        self.caneta = Produto.objects.create(
            usuario=self.user, nome="Caneta", quantidade=50,
            preco_compra=Decimal("2.00"), preco_venda=Decimal("5.00"),
        )
        hoje = timezone.localdate()
        self.venda = registrar_venda(
            usuario=self.user, cliente=self.cliente, itens=[item(self.caneta, 10, "10.00")],
            pagamentos=[
                {"metodo": "pix", "valor": Decimal("40.00"), "data": hoje, "pago": True},
                {"metodo": "credito", "valor": Decimal("60.00"), "data": hoje + timedelta(days=30), "pago": False},
            ],
        )
        self.client.login(username="ana", password=SENHA)
        self.outro = criar_usuario("bia")

    # ---- ordem alfabética dos clientes ----
    def test_clientes_em_ordem_alfabetica_sem_diferenciar_maiusculas(self):
        Cliente.objects.create(usuario=self.user, nome="bruno")
        Cliente.objects.create(usuario=self.user, nome="Ana")
        Cliente.objects.create(usuario=self.user, nome="carla")
        resp = self.client.get(reverse("gestao:cliente_list"))
        nomes = [c.nome for c in resp.context["object_list"]]
        self.assertEqual(nomes, ["Ana", "bruno", "carla", "João da Silva"])

    # ---- histórico ----
    def test_historico_por_ajax_devolve_so_o_miolo(self):
        resp = self.client.get(
            reverse("gestao:cliente_historico", args=[self.cliente.pk]),
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "10× Caneta")
        self.assertContains(resp, "R$ 60,00")  # em aberto
        self.assertNotContains(resp, "<html")

    def test_historico_sem_ajax_e_pagina_completa(self):
        resp = self.client.get(reverse("gestao:cliente_historico", args=[self.cliente.pk]))
        self.assertContains(resp, "<html")
        self.assertContains(resp, "João da Silva")

    def test_historico_de_cliente_de_outro_usuario_da_404(self):
        self.client.logout()
        self.client.login(username="bia", password=SENHA)
        resp = self.client.get(reverse("gestao:cliente_historico", args=[self.cliente.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_lista_de_clientes_tem_botao_historico(self):
        resp = self.client.get(reverse("gestao:cliente_list"))
        self.assertContains(resp, reverse("gestao:cliente_historico", args=[self.cliente.pk]))

    # ---- PDF ----
    def test_pdf_da_venda(self):
        resp = self.client.get(reverse("gestao:venda_pdf", args=[self.venda.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertIn("joao-da-silva", resp["Content-Disposition"])
        self.assertIn("no-store", resp["Cache-Control"])

    def test_dados_do_pdf_nao_vazam_custo_nem_lucro(self):
        from .pdf import dados_pdf_venda

        venda = Venda.objects.prefetch_related("itens__produto", "pagamentos").get(pk=self.venda.pk)
        dados = dados_pdf_venda(venda, "Ana")
        texto = repr(dados).lower()
        self.assertNotIn("custo", texto)
        self.assertNotIn("lucro", texto)
        self.assertEqual(dados["aberto"], "R$ 60,00")
        self.assertEqual(dados["pago"], "R$ 40,00")
        self.assertFalse(dados["quitado"])
        self.assertEqual(len(dados["pagamentos"]), 2)

    def test_pdf_de_venda_de_outro_usuario_da_404(self):
        self.client.logout()
        self.client.login(username="bia", password=SENHA)
        resp = self.client.get(reverse("gestao:venda_pdf", args=[self.venda.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_pdf_com_pagamentos_que_nao_fecham_vai_para_a_edicao(self):
        self.venda.pagamentos.update(valor=Decimal("1.00"))
        resp = self.client.get(reverse("gestao:venda_pdf", args=[self.venda.pk]))
        self.assertRedirects(resp, reverse("gestao:venda_update", args=[self.venda.pk]))

    def test_pdf_com_nome_malicioso_nao_quebra(self):
        self.cliente.nome = "<b>Ana</b> <font size=99999>& <img src=x>"
        self.cliente.save()
        resp = self.client.get(reverse("gestao:venda_pdf", args=[self.venda.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_lista_de_vendas_tem_botao_pdf(self):
        resp = self.client.get(reverse("gestao:venda_list"))
        self.assertContains(resp, reverse("gestao:venda_pdf", args=[self.venda.pk]))
