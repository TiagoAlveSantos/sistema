from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="must_change_password",
            field=models.BooleanField(
                default=False,
                help_text="Quando marcado, o usuário só consegue usar o sistema depois de trocar a senha.",
                verbose_name="exigir troca de senha",
            ),
        ),
    ]
