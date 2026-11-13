from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Perfil com o status de aprovação. Todo novo usuário nasce PENDENTE."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        APPROVED = "approved", "Aprovado"
        REJECTED = "rejected", "Reprovado"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    status = models.CharField(
        "status",
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    avaliado_em = models.DateTimeField("avaliado em", null=True, blank=True)
    avaliado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="perfis_avaliados",
    )

    class Meta:
        verbose_name = "perfil de usuário"
        verbose_name_plural = "perfis de usuário"

    def __str__(self):
        return f"{self.user} ({self.get_status_display()})"

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED
