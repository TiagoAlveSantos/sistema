#!/usr/bin/env python
"""Utilitário de linha de comando do Django para o Sistema Mãe."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django não encontrado. Ative o ambiente virtual "
            "(source venv/bin/activate) e instale as dependências "
            "(pip install -r requirements.txt) antes de rodar este comando."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
