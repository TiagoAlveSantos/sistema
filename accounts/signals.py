from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def criar_perfil(sender, instance, created, **kwargs):
    """Cria o perfil: pendente para usuários comuns, aprovado para superusuários."""
    if created:
        status = (
            UserProfile.Status.APPROVED
            if instance.is_superuser
            else UserProfile.Status.PENDING
        )
        UserProfile.objects.get_or_create(user=instance, defaults={"status": status})
