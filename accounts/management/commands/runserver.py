import os

from django.contrib.sessions.models import Session
from django.core.management.commands.runserver import Command as RunserverCommand
from django.db import DatabaseError


class Command(RunserverCommand):
    help = "Inicia o servidor e encerra todas as sessões abertas (exige novo login)."

    def handle(self, *args, **options):
        # RUN_MAIN só existe no processo filho do autoreload; assim as sessões
        # são limpas uma vez por inicialização, e não a cada recarga de código.
        if os.environ.get("RUN_MAIN") != "true":
            try:
                Session.objects.all().delete()
                self.stdout.write("Sessões anteriores encerradas: login obrigatório.")
            except DatabaseError:
                pass  # banco ainda sem migrações; o runserver já avisa sobre isso
        super().handle(*args, **options)