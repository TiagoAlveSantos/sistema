from .models import UserProfile


def usuarios_pendentes(request):
    """Número de cadastros pendentes (só para o superusuário, exibido no menu)."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_superuser:
        total = UserProfile.objects.filter(
            status=UserProfile.Status.PENDING, user__is_superuser=False
        ).count()
        return {"usuarios_pendentes": total}
    return {}
