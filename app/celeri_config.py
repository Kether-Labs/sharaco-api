import os
import sys
from celery import Celery
from app.core.config import settings

# Ajouter le chemin du projet pour que les imports fonctionnent
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

celery_app = Celery(
    "sharaco",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Beat schedule : vérifier les relances toutes les heures
    beat_schedule={
        "check-reminders": {
            "task": "app.celery_config.check_and_send_reminders",
            "schedule": 3600,  # Toutes les heures (en secondes)
        },
    },
)

celery_app.autodiscover_tasks(["app.celery_tasks"])
