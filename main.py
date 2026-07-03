import time
import yfinance as yf
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ai_routes import router as ai_router

# Importaciones de Base de Datos
from database import engine, Base
from sqlalchemy.exc import OperationalError
import models 

# --- MANEJO DEL CICLO DE VIDA (STARTUP / SHUTDOWN) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Lógica de inicio: Reintentar conexión a la BD
    retries = 5
    for i in range(retries):
        try:
            Base.metadata.create_all(bind=engine)
            print("Base de datos sincronizada con éxito.")
            break
        except OperationalError as e:
            print(f"La base de datos aún no está lista. Reintentando {i+1}/{retries} en 3 segundos...")
            time.sleep(3)
    
    yield # Aquí se ejecuta la aplicación
    
    # Lógica de apagado (si la necesitaras, va aquí)

# --- CONFIGURACIÓN DE FASTAPI ---
app = FastAPI(
    title="Daiko AI Engine Private",
    description="Backend central para gestión de IA y análisis financiero",
    version="2.0",
    lifespan=lifespan # Añadimos el ciclo de vida aquí
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# (El resto de tu código para BolsaEngine y las rutas se mantiene igual)
