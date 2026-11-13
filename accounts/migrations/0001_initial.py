import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendente"),
                            ("approved", "Aprovado"),
                            ("rejected", "Reprovado"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=10,
                        verbose_name="status",
                    ),
                ),
                (
                    "avaliado_em",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="avaliado em"
                    ),
                ),
                (
                    "avaliado_por",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="perfis_avaliados",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "perfil de usuário",
                "verbose_name_plural": "perfis de usuário",
            },
        ),
    ]
