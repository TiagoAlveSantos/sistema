# Sistema Mãe

Sistema web multiusuário para pequenos vendedores (revendedores de cosméticos, por exemplo) gerenciarem **clientes, prospecções, estoque e vendas**, com painel de métricas. Cada usuário enxerga **somente os próprios dados** e novos cadastros só entram depois de aprovados por um administrador.

> Desenvolvido com apoio de IA: o código foi construído com **Claude** (Anthropic) e **Gemini** (Google), com revisão e decisões de projeto do autor.

## Funcionalidades

### Contas e administração
- **Cadastro com aprovação:** todo novo usuário cria a própria senha e nasce *pendente*; só entra depois que o administrador aprovar (ou reprovar — o que derruba também as sessões abertas).
- **Captcha no cadastro (opcional):** Cloudflare Turnstile, gratuito. Fica desligado se as chaves não forem configuradas.
- **Painel do administrador** (`/contas/painel/`): aprova/reprova usuários, **exige a troca de senha** de um usuário ou **define uma senha temporária**. O administrador **não vê** clientes, prospecções, estoque nem vendas de ninguém e nunca vê a senha de ninguém.
- **Troca de senha obrigatória:** com a exigência ativa, o usuário só acessa a tela de troca (ou o logout) até definir uma nova senha. Todo usuário também pode trocar a própria senha pelo menu.
- **Isolamento total de dados:** todo registro pertence a um usuário; acessar o registro de outro retorna 404.

### Módulos
- **Clientes:** nome, CPF (validado e único por usuário), e-mail, telefone, endereço; busca por nome, CPF, e-mail ou telefone.
- **Prospecções:** vinculadas a um cliente, com status, datas de contato/novo contato e telefone.
- **Estoque:** quantidade, preço de compra (custo) e preço de venda sugerido; exclusão de itens que nunca foram vendidos. Se o estoque mudar enquanto você edita um item, o sistema avisa em vez de sobrescrever.
- **Vendas com vários itens:** cada venda tem cliente, data/hora (inclusive retroativa) e **quantos itens quiser**, cada um com quantidade e preço próprios (o preço sugerido vem preenchido, mas pode ser alterado). O estoque é debitado automaticamente e o lucro de cada item é `(preço praticado − custo) × quantidade`; o custo unitário fica gravado na venda, então alterar o custo depois não muda o histórico.
  - **Lista:** uma linha por venda; a setinha à esquerda abre os itens daquela venda.
  - **Edição:** o produto e o custo de cada item ficam travados; é possível mudar quantidade e preço (respeitando o estoque), o cliente e a data, e adicionar itens novos.
  - **Reverter:** reverte a venda inteira ou **um item** individualmente (o estoque volta). Se sobrar um único item, só a reversão da venda inteira é oferecida.
  - **Pagamentos:** cada venda pode ser paga por vários meios e em várias datas (Pix, dinheiro, cartão…, à vista ou **parcelada**), cada linha **paga** ou **pendente** para uma data. A soma precisa fechar com o total. Pendências são confirmadas na lista de vendas ("Confirmar recebimento"); há filtro por situação (pendente, atrasado, quitado, a ajustar).
  - **PDF da venda:** botão "PDF" em cada venda gera um resumo para enviar ao cliente (itens, valores, o que já foi pago, o que está em aberto e o vencimento de cada parcela). Nunca mostra custo nem lucro.
- **Clientes:** lista em ordem alfabética e botão **Histórico**, que abre por cima da lista as compras do cliente (total comprado, valor em aberto).
- **Dashboard:** vendas, lucro, prospecções, clientes e clientes distintos que compraram, com **filtro de ano e de mês** (só aparecem períodos com vendas, ou "Todos"), e o **valor atual do estoque a preço de custo**. Também mostra **Recebido**, **A receber** e **Em atraso**.

## Tecnologias

Python · Django 5.2 LTS · PostgreSQL (Neon) em produção / SQLite local · Gunicorn · WhiteNoise · django-axes · Bootstrap 5 (CDN) · Flatpickr (CDN) · Cloudflare Turnstile (opcional).

## Segurança

- CSRF, XSS (autoescape), SQL Injection (ORM) e hash de senhas nativos do Django.
- Bloqueio por tentativas de login (django-axes: 5 falhas, 30 min).
- Backend de autenticação próprio (`ApprovedUserBackend`) que só aceita usuários aprovados.
- Operações de venda atômicas, com `UPDATE` condicional de estoque (seguro contra concorrência) e limites numéricos que impedem estouro dos campos do banco.
- Em produção: cookies seguros, redirecionamento HTTPS, **HSTS** e `DEBUG` desligado.
- Arquivos de CDN com **versão fixada e SRI** (o navegador recusa arquivos alterados).
- `django.contrib.admin` **não** está instalado, de propósito.

## Variáveis de ambiente

| Variável | Uso |
|---|---|
| `DATABASE_URL` | URL do PostgreSQL (Neon). Sem ela, usa SQLite local. |
| `DJANGO_SECRET_KEY` | Chave secreta. **Obrigatória no Render** (o sistema não inicia sem ela). |
| `DJANGO_DEBUG` | `1` ativa o modo debug (apenas local). |
| `DJANGO_ALLOWED_HOSTS` | Hosts extras, separados por vírgula. |
| `DJANGO_HSTS_SECONDS` | Duração do HSTS em produção. Padrão `3600` (1 h); depois de validar, use `31536000` (1 ano). |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | Chaves do captcha (opcionais; sem as duas, o captcha fica desligado). |
| `PYTHON_VERSION` | (Render) versão do Python, para o build não mudar sozinho. |
| `RENDER` / `RENDER_EXTERNAL_HOSTNAME` | Definidas automaticamente pelo Render. |

## Rodando localmente

**Linux/macOS**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # administrador
python manage.py runserver
```

Acesse http://127.0.0.1:8000/. Cadastre um usuário comum pela tela de registro e aprove-o logado como administrador.

## Testes

```bash
python manage.py test
```

## Deploy (Render + Neon)

1. Crie o projeto no **Neon** e copie a `DATABASE_URL` (use a mesma região do servidor do Render, por exemplo *US East*; regiões distantes deixam o login lento).
2. No **Render**, crie um *Web Service* a partir deste repositório:
   - Build: `pip install -r requirements.txt && python manage.py migrate`
   - Start: `gunicorn config.wsgi`
   - Variáveis: `DATABASE_URL`, `DJANGO_SECRET_KEY` (e, se quiser, `PYTHON_VERSION`, `DJANGO_HSTS_SECONDS`, `TURNSTILE_*`).
3. Crie o administrador uma vez (`python manage.py createsuperuser`) localmente apontando para a mesma `DATABASE_URL`, ou insira-o por SQL com o hash gerado pelo Django.

No plano gratuito o servidor "dorme" após inatividade e o primeiro acesso demora.

### Captcha gratuito (Cloudflare Turnstile)
1. Crie uma conta gratuita no Cloudflare e, em **Turnstile**, adicione um site com o domínio do Render.
2. Copie a *Site Key* e a *Secret Key* para as variáveis `TURNSTILE_SITE_KEY` e `TURNSTILE_SECRET_KEY` no Render.
3. A tela de cadastro passa a exibir o captcha automaticamente.

### Atualizando bibliotecas de CDN (SRI)
Ao mudar a versão do Bootstrap ou do Flatpickr nos templates, rode (precisa de internet):

```bash
python tools/gerar_sri.py --aplicar   # grava os hashes nos templates
python tools/gerar_sri.py             # apenas confere
```

### Conferindo o IP do bloqueio de login (Axes)
Depois de errar a senha uma vez em produção, consulte no SQL Editor do Neon:
`SELECT ip_address, failures_since_start FROM axes_accessattempt;`
O IP deve ser o seu, e não o de um proxy do Render. Se for o do proxy, ajuste `AXES_IPWARE_PROXY_COUNT` em `config/settings.py`.

## Estrutura

```
config/      configurações, URLs, WSGI
accounts/    cadastro, login, aprovação, senhas, painel do admin
gestao/      clientes, prospecções, estoque, vendas, dashboard
templates/   HTML (Bootstrap)
tools/       utilitários (SRI dos arquivos de CDN)
```

## Licença

Software **de código disponível, com royalties em caso de uso comercial** — leia o arquivo [LICENSE](LICENSE). Uso pessoal e educacional é gratuito.

## Créditos

Autor: Tiago Alves dos Santos. Desenvolvido com auxílio de Claude (Anthropic) e Gemini (Google).
