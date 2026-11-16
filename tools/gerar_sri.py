"""
Gera/confere o SRI (Subresource Integrity) dos arquivos carregados de CDN.

SRI é uma "impressão digital" do arquivo: se a CDN entregar um arquivo diferente
do esperado (alterado, adulterado), o navegador se recusa a executá-lo.

Uso (precisa de internet; só usa a biblioteca padrão do Python):

    python tools/gerar_sri.py            # confere; mostra o que falta ou diverge
    python tools/gerar_sri.py --aplicar  # grava/atualiza integrity="..." nos templates

Rode `--aplicar` sempre que mudar a versão de um arquivo de CDN, e faça commit.
"""
import base64
import hashlib
import re
import sys
import urllib.request
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
# <link ... href="https://cdn.jsdelivr.net/..."> ou <script ... src="https://cdn.jsdelivr.net/...">
TAG = re.compile(r'<(?:link|script)\b[^>]*?(?:href|src)="(https://cdn\.jsdelivr\.net/[^"]+)"[^>]*>')
VERSAO_FIXA = re.compile(r"@\d+\.\d+\.\d+")


def sri(url):
    with urllib.request.urlopen(url, timeout=30) as resposta:  # noqa: S310 (https fixo)
        corpo = resposta.read()
    return "sha384-" + base64.b64encode(hashlib.sha384(corpo).digest()).decode()


def sem_atributos(tag):
    tag = re.sub(r'\s+integrity="[^"]*"', "", tag)
    return re.sub(r'\s+crossorigin="[^"]*"', "", tag)


def main():
    aplicar = "--aplicar" in sys.argv
    problemas = 0
    for arquivo in sorted(TEMPLATES.rglob("*.html")):
        texto = arquivo.read_text(encoding="utf-8")
        novo = texto
        for tag in TAG.finditer(texto):
            original, url = tag.group(0), tag.group(1)
            if not VERSAO_FIXA.search(url):
                print(f"[VERSÃO NÃO FIXADA] {arquivo.name}: {url}")
                problemas += 1
                continue
            esperado = sri(url)
            atual = re.search(r'integrity="([^"]*)"', original)
            if atual and atual.group(1) == esperado:
                print(f"[OK] {arquivo.name}: {url}")
                continue
            if aplicar:
                limpa = sem_atributos(original)
                nova = limpa[:-1].rstrip() + f' integrity="{esperado}" crossorigin="anonymous">'
                novo = novo.replace(original, nova)
                print(f"[GRAVADO] {arquivo.name}: {url}")
            else:
                estado = "DIVERGE" if atual else "SEM INTEGRITY"
                print(f"[{estado}] {arquivo.name}: {url}\n          correto: {esperado}")
                problemas += 1
        if aplicar and novo != texto:
            arquivo.write_text(novo, encoding="utf-8")
    if problemas:
        print(f"\n{problemas} pendência(s). Rode com --aplicar para corrigir.")
        return 1
    print("\nTudo certo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
