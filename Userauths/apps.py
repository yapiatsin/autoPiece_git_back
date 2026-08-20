from django.apps import AppConfig

class UserauthsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Userauths'
    def ready(self):
        import Userauths.signals
        return super().ready()
