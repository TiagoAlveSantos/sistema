# Sistema Mãe

Sistema web multiusuário para pequenos vendedores (revendedores de cosméticos, por exemplo) gerenciarem **clientes, prospecções, estoque e vendas**, com painel de métricas mensais. Cada usuário enxerga **somente os próprios dados** e novos cadastros só entram depois de aprovados por um administrador.

> Desenvolvido com apoio de IA: o código foi construído com **Claude** (Anthropic) e **Gemini** (Google), com revisão e decisões de projeto do autor.

## Funcionalidades

- **Cadastro com aprovação:** todo novo usuário nasce *pendente* e não consegue entrar até o administrador aprovar (ou reprovar — o que derruba também sessões abertas).
- **Painel do administrador** (`/contas/painel/`): só gerencia usuários. O administrador **não vê** clientes, prospecções, estoque nem vendas de ninguém.
- **Isolamento total de dados:** todo registro pertence a um usuário; acessar o registro de outro retorna 404.
- **Clientes:** nome, CPF (validado e único por usuário), e-mail, telefone, endereço, busca.
- **Prospecções:** vinculadas a um cliente, com status, datas de contato/novo contato e telefone.
- **Estoque:** quantidade, preço de compra e preço de venda sugerido.
- **Vendas:** escolha do item, preço editável na hora, data/hora (inclusive retroativa), débito automático do estoque e lucro = (preço praticado − custo) × quantidade. O custo unitário fica gravado na venda, então alterar o custo depois não muda o histórico.
  - **Edição:** produto e data originais são mantidos; a quantidade só pode mudar se houver estoque (o estoque é ajustado pela diferença).
  - **Reverter:** devolve a quantidade ao estoque.
- **Dashboard:** vendas, lucro, prospecções, total de clientes e clientes distintos que compraram no mês, com seletor de mês (a partir da criação da conta).

## Tecnologias

Python · Django 5.2 LTS · PostgreSQL (Neon) em produção / SQLite local · Gunicorn · WhiteNoise · django-axes · Bootstrap 5 (CDN) · Flatpickr (CDN).

## Segurança

- CSRF, XSS (autoescape), SQL Injection (ORM) e hash de senhas nativos do Django.
- Bloqueio por tentativas de login (django-axes: 5 falhas, 30 min).
- Backend de autenticação próprio (`ApprovedUserBackend`) que só aceita usuários aprovados.
- Operações de venda atômicas, com `UPDATE` condicional de estoque (seguro contra concorrência).
- Em produção: cookies seguros, redirecionamento HTTPS e `DEBUG` desligado.
- `django.contrib.admin` **não** está instalado, de propósito.

## Variáveis de ambiente

| Variável | Uso |
|---|---|
| `DATABASE_URL` | URL do PostgreSQL (Neon). Sem ela, usa SQLite local. |
| `DJANGO_SECRET_KEY` | Chave secreta (obrigatória em produção). |
| `DJANGO_DEBUG` | `1` ativa o modo debug (apenas local). |
| `DJANGO_ALLOWED_HOSTS` | Hosts extras, separados por vírgula. |
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

**Windows:** execute `install.bat` (cria o venv, instala dependências, migra o banco e oferece criar o administrador) e depois `run.bat`.

Acesse http://127.0.0.1:8000/. Cadastre um usuário comum pela tela de registro e aprove-o logado como administrador.

## Testes

```bash
python manage.py test
```

## Deploy (Render + Neon)

1. Crie o projeto no **Neon** e copie a `DATABASE_URL`.
2. No **Render**, crie um *Web Service* a partir deste repositório:
   - Build: `pip install -r requirements.txt && python manage.py migrate`
   - Start: `gunicorn config.wsgi`
   - Variáveis: `DATABASE_URL`, `DJANGO_SECRET_KEY`.
3. Crie o administrador uma vez (`python manage.py createsuperuser`) no Shell ou localmente apontando para a mesma `DATABASE_URL`.

**Dica de desempenho:** escolha a região do banco e a do servidor próximas (ex.: ambos em *US East*). Bancos e servidores em regiões distantes deixam o login lento, pois cada consulta paga a latência. No plano gratuito o servidor "dorme" após inatividade e o primeiro acesso demora.

## Estrutura

```
config/      configurações, URLs, WSGI
accounts/    cadastro, login, aprovação, painel do admin
gestao/      clientes, prospecções, estoque, vendas, dashboard
templates/   HTML (Bootstrap)
```

## Licença

Software **de código disponível, com royalties em caso de uso comercial** — leia o arquivo [LICENSE](LICENSE). Uso pessoal e educacional é gratuito.

## Créditos

Autor: Tiago Alves Santos. Desenvolvido com auxílio de Claude (Anthropic) e Gemini (Google).
