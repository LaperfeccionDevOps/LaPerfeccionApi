# app/main_clean.py
from fastapi import FastAPI
from app.api.routers.aspirante_routers import router as aspirante_router
from infrastructure.db.base import Base
from infrastructure.db.session import engine

app = FastAPI(title="La Perfeccion - Backend")

# SOLO en desarrollo (mientras no uses Alembic):
Base.metadata.create_all(bind=engine)

# Rutas
app.include_router(aspirante_router, prefix="/api", tags=["aspirantes"])

@app.get("/ping")
def ping():
    return {"ok": True}