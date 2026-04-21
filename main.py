from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.auth import router as auth_router
from app.api.v1.client import router as client_router

app = FastAPI(title="Sharaco API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔗 INCLUSION DES ROUTERS
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(client_router, prefix="/api/v1/clients", tags=["clients"])


@app.get("/")
async def root():
    return {"message": "Welcome to Sharaco API", "version": "0.1.0"}
