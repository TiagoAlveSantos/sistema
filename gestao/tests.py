from datetime import datetime, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.testutils import SENHA, User, criar_admin, criar_usuario, sem_axes

from .models import Cliente, ItemVenda, Produto, Prospeccao, Venda
from .services import registrar_venda


def agora_str():
    """Data/hora atual no formato que o formulário de venda envia (AAAA-MM-DD HH:MM)."""
    return timezone.localtime().strftime("%Y-%m-%d %H:%M")


def item(produto, quantidade, preco):
    """Linha de venda no formato esperado por registrar_venda()."""
    return {"produto": produto, "quantidade": quantidade, "preco": Decimal(preco)}


def dados_venda(cliente, linhas, data=None, iniciais=0):
    """
    Monta o POST do formulário de venda (cabeçalho + formset 'itens').
    Cada linha: {"produto": Produto|None, "quantidade": n, "preco": "x.xx", "item_id": id|None}.
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
        self.assertRedirects(resp, reverse("gestao:venda_list"))
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
