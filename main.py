# app/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.db.engine import async_session  # ⚠️ adapte selon ton chemin
from app.services.overdueService import OverdueService

# Routers
from app.api.v1.auth import router as auth_router
from app.api.v1.client import router as client_router
from app.api.v1.template import router as template_router
from app.api.v1.document import router as document_router
from app.api.v1.reminder import router as reminder_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.project import router as project_router
from app.api.v1.activity import router as activity_router
from app.api.v1.billing_settings import router as billing_settings_router
from app.api.v1.payment_schedule import router as payment_schedule_router
from app.api.v1.cron import router as cron_router  # ⚠️ à ajouter si pas fait

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# APScheduler : jobs quotidiens
# ═══════════════════════════════════════════════════════════════
scheduler = AsyncIOScheduler(timezone="UTC")


async def _job_check_overdue():
    """Job quotidien : marque les factures en retard."""
    logger.info("⏰ Cron OVERDUE démarré")
    async with async_session() as db:
        summary = await OverdueService.check_overdue_invoices(db)
        logger.info(f"🔴 Cron OVERDUE terminé: {summary}")


# ═══════════════════════════════════════════════════════════════
# Lifespan (remplace @app.on_event startup/shutdown)
# ═══════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ===== STARTUP =====
    logger.info("🚀 Démarrage de Sharaco API")
    
    # Démarrer le scheduler
    scheduler.add_job(
        _job_check_overdue,
        CronTrigger(hour=0, minute=5),  # Tous les jours à 00:05 UTC
        id="check_overdue",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("⏰ Scheduler démarré (OVERDUE à 00:05 UTC)")
    
    yield
    
    # ===== SHUTDOWN =====
    logger.info("🛑 Arrêt de Sharaco API")
    scheduler.shutdown()


# ═══════════════════════════════════════════════════════════════
# App FastAPI
# ═══════════════════════════════════════════════════════════════
app = FastAPI(
    title="Sharaco API", 
    version="0.1.0",
    lifespan=lifespan,  # ← important
)

# ═══════════════════════════════════════════════════════════════
# Middlewares
# ═══════════════════════════════════════════════════════════════
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    https_only=False,
    max_age=3600,
    same_site="lax",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════
# Routers
# ═══════════════════════════════════════════════════════════════
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(client_router, prefix="/api/v1/clients", tags=["clients"])
app.include_router(template_router, prefix="/api/v1/templates", tags=["templates"])
app.include_router(document_router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(reminder_router, prefix="/api/v1/reminders", tags=["reminders"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(project_router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(activity_router, prefix="/api/v1/activity", tags=["activity"])
app.include_router(billing_settings_router, prefix="/api/v1/billing-settings", tags=["billing-settings"])
app.include_router(payment_schedule_router, prefix="/api/v1/payment-schedule", tags=["payment-schedule"])
app.include_router(cron_router, prefix="/api/v1/cron", tags=["cron"])  # ← AJOUTÉ


@app.get("/")
async def root():
    return {"message": "Welcome to Sharaco API", "version": "0.1.0"}