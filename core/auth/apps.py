from django.apps import AppConfig


class AuthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.auth'
    label = 'core_auth'  # Unique label to avoid conflict with Django's built-in auth

