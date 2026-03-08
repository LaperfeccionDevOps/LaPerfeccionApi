from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers.auth import router as auth_router
from api.routers.aspirante_routers import router as aspirante_router
from api.routers.consultar_combos_routers import router as consultar_combos_router
from api.routers.cita_routers import router as cita_router
from api.routers.entrevista_routers import router as entrevista_router
from api.routers import estado_proceso_routers
from api.routers.experiencia_laboral_routers import router as experiencia_laboral_router
from api.routers.nucleo_familiar_routers import router as nucleo_familiar_router
from api.routers.documentos_ingreso_routers import router as documentos_ingreso_router
from api.routers.contratacion_registro_routers import router as contratacion_registro_router
from api.routers.asignacion_cargo_cliente_routers import router as asignacion_cargo_cliente_router
from api.routers.referencia_personal_validacion_routers import router as ref_pers_val_router
from api.routers.experiencia_laboral_validacion_routers import router as experiencia_laboral_validacion_router
from api.routers.perfil_aspirante_routers import router as perfil_aspirante_router
from api.routers.datos_proceso_aspirante_routers import router as datos_proceso_aspirante_router
from api.routers.documentos_seguridad_routers import router as documentos_seguridad_router
from api.routers.contratos_obra_labor_routers import router as contratos_obra_labor_router
from api.routers.entrevistas_candidato_routers import router as entrevistas_candidato_router
from api.routers.motivo_cierre_routers import router as motivo_cierre_router
from api.routers.observaciones_nucleo_familiar_routers import router as obs_nf_router
from api.routers.observaciones_experiencia_laboral_routers import router as observaciones_experiencia_laboral_router
from api.routers.contratacion_basica_routers import router as contratacion_basica_router
from api.routers.datos_seleccion_routers import router as datos_seleccion_router
from api.routers.formacion_educacion_routers import router as formacion_educacion_router
from api.routers.tratamiento_datos_routers import router as tratamiento_datos_router
from api.routers.descargar_documentos_routers import router as descargar_documentos_router
from api.routers.documentos_contratacion_routers import router as subir_documento_contratacion
from api.routers.rechazo_contratacion_routers import router as rechazo_contratacion_router
from api.routers.contratado_routers import router as contratado_router
from api.routers.configuracion_routers import router as configuracion_router
from api.routers import retiro_laboral_routers
from api.routers.rrll_busqueda_routers import router as rrll_busqueda_router


app = FastAPI(
    title="La Perfeccion - Backend",
    version="1.0.0",
    description="API para gestión de colaboradores, procesos de selección y portal interno.",
    debug=True,
)

origins = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.10.104:3000",
    "http://192.168.80.173:3000",
    "http://192.168.20.33:3000/",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://192.168.10.231:3001",
    "http://192.168.10.210:8302",
    "http://localhost:5173",
    "https://laperfeccion.app",
]

app.add_middleware(
    ProxyHeadersMiddleware,
    trusted_hosts="*"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# 📌 Routers
# ─────────────────────────────────────────────
app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(aspirante_router, prefix="/api", tags=["aspirantes"])
app.include_router(consultar_combos_router, prefix="/api", tags=["combos"])
app.include_router(cita_router, prefix="/api", tags=["citas"])
app.include_router(entrevista_router, prefix="/api", tags=["entrevistas"])
app.include_router(estado_proceso_routers.router, prefix="/api", tags=["estados proceso"])
app.include_router(nucleo_familiar_router, prefix="/api", tags=["nucleo-familiar"])
app.include_router(observaciones_experiencia_laboral_router, prefix="/api")
app.include_router(contratacion_basica_router)
app.include_router(datos_seleccion_router)
app.include_router(experiencia_laboral_validacion_router)
app.include_router(formacion_educacion_router)
app.include_router(tratamiento_datos_router)
app.include_router(descargar_documentos_router)
app.include_router(contratado_router)
app.include_router(experiencia_laboral_router,prefix="/api",tags=["experiencia-laboral"])
app.include_router(ref_pers_val_router)
app.include_router(experiencia_laboral_validacion_router)
app.include_router(perfil_aspirante_router)
app.include_router(datos_proceso_aspirante_router, prefix="/api", tags=["datos-proceso-aspirante"])
app.include_router(documentos_ingreso_router)
app.include_router(contratacion_registro_router)
app.include_router(asignacion_cargo_cliente_router)
app.include_router(documentos_seguridad_router)
app.include_router(contratos_obra_labor_router)
app.include_router(entrevistas_candidato_router)
app.include_router(motivo_cierre_router)
app.include_router(obs_nf_router, prefix="/api")
app.include_router(subir_documento_contratacion, prefix="/api")
app.include_router(rechazo_contratacion_router)
app.include_router(configuracion_router, prefix="/api")
app.include_router(retiro_laboral_routers.router)
app.include_router(rrll_busqueda_router)

# ─────────────────────────────────────────────
# Endpoints básicos de salud
# ─────────────────────────────────────────────
@app.get("/")
def root():
    """
    Endpoint raíz de la API.
    """
    return {
        "ok": True,
        "message": "API operativa. Bienvenido a la API de La Perfeccion. Ve a /docs",
    }

    """
    Endpoint raíz de la API.
    """
    return {
        "ok": True,
        "message": "API operativa. Bienvenido a la API de La Perfeccion. Ve a /docs",
    }
