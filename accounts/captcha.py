"""Cloudflare Turnstile (captcha gratuito) para a tela de cadastro."""
import json
import urllib.parse
import urllib.request

from django.conf import settings

URL_VERIFICACAO = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def captcha_ativo():
    """Só exige o captcha se as duas chaves estiverem configuradas."""
    return bool(settings.TURNSTILE_SITE_KEY and settings.TURNSTILE_SECRET_KEY)


def verificar(token):
    """True se o Cloudflare confirmar o token. Qualquer falha (rede, resposta ruim) = False."""
    if not token:
        return False
    corpo = urllib.parse.urlencode(
        {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    ).encode()
    pedido = urllib.request.Request(URL_VERIFICACAO, data=corpo, method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=5) as resposta:  # noqa: S310 (URL fixa https)
            return bool(json.load(resposta).get("success"))
    except Exception:
        return False
