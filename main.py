from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ai_routes import router as ai_router

# --- NUEVAS IMPORTACIONES PARA LA BASE DE DATOS ---
from database import engine, Base
import models  # <--- VITAL: Carga las definiciones de las tablas (User, AIChatHistory, etc.)

# --- ESTA LÍNEA ES EL MOTOR ---
# Revisa la base de datos en Render y crea las tablas que falten automáticamente
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Daiko AI Engine Private")

# Configuración de CORS: Permite que tu app de Flutter se conecte sin bloqueos
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Conectamos las rutas de la IA que ya tienen la seguridad JWT
app.include_router(ai_router)

@app.get("/")
def health_check():
    return {
        "status": "online", 
        "engine": "Daiko 2.0", 
        "owner": "Kevin Guevara",
        "database": "connected and synced"
    }