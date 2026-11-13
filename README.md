# Sistema Mãe

Sistema web (Django 5.2 LTS + SQLite) para gestão de clientes, prospecções, estoque e vendas, com
aprovação de usuários pelo administrador e **isolamento total de dados entre usuários**.

## Instalação no Windows

Pré-requisito: Python 3.10 ou superior (marque *Add python.exe to PATH* ao instalar).

1. Dê dois cliques em **`install.bat`**. Ele cria o `venv`, instala o `requirements.txt`, roda as
   migrações e pergunta se você quer criar o primeiro Administrador.
2. Para usar, dê dois cliques em **`run.bat`** (abre o servidor em <http://127.0.0.1:8000/> e o navegador).

Sem o instalador: `python -m venv venv`, `venv\Scripts\activate`, `pip install -r requirements.txt`,
`python manage.py migrate`, `python manage.py createsuperuser`, `python manage.py runserver`.

## Como funciona o acesso

- Qualquer pessoa pode se cadastrar em `/contas/registro/`, mas a conta **nasce pendente** e não consegue entrar.
- O Administrador (superusuário) entra e vê o menu **Usuários** (`/contas/painel/`), com abas
  Pendentes / Aprovados / Reprovados e botões Aprovar / Reprovar.
- Reprovar derruba a sessão do usuário na hora (o backend de login é revalidado a cada requisição).
- O Administrador **não acessa** clientes, prospecções, estoque nem vendas: esses módulos redirecionam
  superusuários ao painel, e nenhum modelo de negócio é exposto (o Django Admin nem está instalado).

## Estrutura

```
sistema_mae/
├── manage.py
├── requirements.txt
├── install.bat / run.bat
├── config/            settings.py (seguro por padrão), urls.py, wsgi.py
├── accounts/          cadastro, login, aprovação
│   ├── models.py        UserProfile (status: pending/approved/rejected)
│   ├── signals.py       cria o perfil (pendente; superusuário nasce aprovado)
│   ├── backends.py      só autentica usuários aprovados
│   ├── permissions.py   superuser_required, usuario_comum_required, mixin
│   ├── forms.py / views.py / urls.py
├── gestao/            módulos de negócio
│   ├── models.py        Cliente, Prospeccao, Produto, Venda (+ DonoQuerySet.do_usuario)
│   ├── services.py      registrar_venda() atômica
│   ├── mixins.py        isolamento por usuário nas views
│   ├── forms.py / views.py / urls.py
└── templates/         base.html (Bootstrap 5), partials/, accounts/, gestao/, 403/404/500
```

## Segurança e isolamento

- **CSRF, XSS, SQL Injection e hash de senha**: middleware CSRF e `{% csrf_token %}` em todo POST; autoescape
  dos templates; ORM parametrizado; PBKDF2 do Django + validadores de senha.
- **Isolamento**: todo modelo de negócio tem `usuario` (FK, `editable=False`). As views filtram por
  `do_usuario(request.user)`, então o registro de outro usuário responde **404**. O dono é sempre
  `request.user`, nunca vem do POST. Campos de relação (cliente na prospecção/venda, item na venda) só
  aceitam registros do próprio usuário.
- **Login obrigatório** em todas as views (`login_required` / `LoginRequiredMixin`); ações do painel só por
  POST e só para superusuário.
- **SECRET_KEY** gerada na primeira execução e guardada em `.secret_key`; `DEBUG` desligado por padrão
  (`DJANGO_DEBUG=1` para depurar); `ALLOWED_HOSTS` restrito a localhost.

## Regras de negócio

- **Venda** (`gestao/services.py`): em uma transação, debita o estoque com `UPDATE` condicional
  (impede estoque negativo mesmo com duas vendas simultâneas), grava o custo unitário do momento e calcula
  `lucro = (preço praticado − preço de compra) × quantidade`. O preço sugerido vem do cadastro e pode ser alterado.
- **Dashboard**: vendas, lucro, prospecções (por data do contato) e clientes compradores distintos no mês
  escolhido. O seletor lista do mês atual até o mês de criação da conta. "Clientes cadastrados" conta os
  cadastrados até o fim do mês selecionado (no mês atual, é o total).
- Não há exclusão de clientes, itens ou vendas, de propósito: preserva o histórico e a consistência do estoque.

## Testes

```
venv\Scripts\activate
python manage.py test
```

Cobrem aprovação/bloqueio de login, derrubada de sessão ao reprovar, isolamento entre usuários,
bloqueio do superusuário nos módulos de negócio, venda (estoque e lucro) e métricas do dashboard.

## Limitações conhecidas

- O isolamento é **na aplicação**: quem tiver acesso ao arquivo `db.sqlite3` no disco consegue ler tudo.
- O visual usa Bootstrap via CDN, então precisa de internet no navegador.
- Não há bloqueio por tentativas de login; para exposição fora do localhost, considere `django-axes`,
  HTTPS e um servidor de produção (o `runserver` é só para uso local).
