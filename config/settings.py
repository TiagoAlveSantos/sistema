import os
from pathlib import Path
import dj_database_url

from django.contrib.messages import constants as message_constants
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent


def _obter_secret_key():
    """Variável de ambiente > arquivo .secret_key > gera uma nova e grava."""
    da_env = os.environ.get("DJANGO_SECRET_KEY")
    if da_env:
        return da_env
    arquivo = BASE_DIR / ".secret_key"
    if arquivo.exists():
        chave = arquivo.read_text(encoding="utf-8").strip()
        if chave:
            return chave
    chave = get_random_secret_key()
    arquivo.write_text(chave, encoding="utf-8")
    return chave


SECRET_KEY = _obter_secret_key()

# Seguro por padrão: DEBUG desligado no Render, ligado localmente se solicitado.
DEBUG = 'RENDER' not in os.environ

# Host permitidos (Render + Local)
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

custom_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
if custom_hosts:
    ALLOWED_HOSTS += [h.strip() for h in custom_hosts.split(",") if h.strip()]

# --------------------------------------------------------------------------
# Aplicativos
# NOTA DE SEGURANÇA: django.contrib.admin NÃO está instalado de propósito.
# A administração de usuários é feita pela tela própria (/contas/painel/), e
# nenhum modelo de negócio fica exposto ao superusuário.
# --------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles", # Necessário para arquivos estáticos
    "accounts.apps.AccountsConfig",
    "gestao.apps.GestaoConfig",
    "axes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # Essencial para arquivos estáticos no Render
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",  # proteção CSRF
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            # Autoescape do Django ligado por padrão -> proteção contra XSS.
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "accounts.context_processors.usuarios_pendentes",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Banco de dados (PostgreSQL no Neon via DATABASE_URL ou SQLite local)
# --------------------------------------------------------------------------
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# --------------------------------------------------------------------------
# Autenticação
# --------------------------------------------------------------------------
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "gestao:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# --------------------------------------------------------------------------
# Arquivos Estáticos (CSS, JS, Imagens) com WhiteNoise
# --------------------------------------------------------------------------
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# --------------------------------------------------------------------------
# Sessão / cookies
# --------------------------------------------------------------------------
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8 horas
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# O Render fornece HTTPS nativo, portanto ative estas opções de segurança de cookie:
if 'RENDER' in os.environ:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True

# --------------------------------------------------------------------------
# Internacionalização
# --------------------------------------------------------------------------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
USE_THOUSAND_SEPARATOR = True

MESSAGE_TAGS = {message_constants.ERROR: "danger"}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Número máximo de tentativas permitidas antes do bloqueio
AXES_FAILURE_LIMIT = 5

# Desbloqueia automaticamente após 30 minutos (0.5 hora)
# Você pode usar números decimais (0.5 = 30 min) ou timedelta(minutes=30)
AXES_COOLOFF_TIME = 0.5

# Reseta o contador de erros assim que o usuário faz um login com sucesso
AXES_RESET_ON_SUCCESS = True

#Remove o log dele para tentar deixar mais rápido
AXES_DISABLE_ACCESS_LOG = True