import asyncio
import traceback
import yfinance as yf
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ai_routes import router as ai_router

# Importaciones de Base de Datos
from database import engine, Base
from sqlalchemy.exc import OperationalError
import models 

# --- MANEJO DEL CICLO DE VIDA (STARTUP / SHUTDOWN) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Lógica de inicio: Reintentar conexión a la BD de forma asíncrona
    retries = 10
    for i in range(retries):
        try:
            Base.metadata.create_all(bind=engine)
            print("Base de datos sincronizada con éxito.")
            break
        except OperationalError as e:
            print(f"La base de datos aún no está lista. Reintentando {i+1}/{retries} en 5 segundos...")
            await asyncio.sleep(5)
    
    yield # Aquí se ejecuta la aplicación
    
    # Lógica de apagado (si la necesitaras, va aquí)

# --- MOTOR DE ANÁLISIS DE BOLSA ---
class BolsaEngine:
    """
    Motor de análisis de bolsa independiente para Daiko AI.
    """
    @staticmethod
    def obtener_precio_actual(ticker_simbolo: str):
        ticker = yf.Ticker(ticker_simbolo)
        data = ticker.history(period="1d")
        if data.empty:
            return None
        return round(data['Close'].iloc[-1], 2)

    @staticmethod
    def obtener_analisis_completo(ticker_simbolo: str):
        ticker = yf.Ticker(ticker_simbolo)
        hist = ticker.history(period="5d")
        
        if hist.empty:
            return {"error": "Símbolo no encontrado o sin datos"}

        # Intentar obtener info (maneja errores si la API de Yahoo falla)
        try:
            info = ticker.info
        except:
            info = {}

        precio_actual = hist['Close'].iloc[-1]
        precio_inicial = hist['Close'].iloc[0]
        rendimiento_semanal = ((precio_actual - precio_inicial) / precio_inicial) * 100

        return {
            "simbolo": ticker_simbolo,
            "nombre": info.get('longName', ticker_simbolo),
            "precio_actual": round(precio_actual, 2),
            "tendencia_semanal_pct": round(rendimiento_semanal, 2),
            "sector": info.get('sector', 'Desconocido'),
            "resumen": info.get('longBusinessSummary', 'Sin descripción')[:200] + "..."
        }

# --- FUNCIÓN QUE USARÁ GEMINI ---
def obtener_analisis_bolsa(ticker: str):
    """
    Consulta información financiera en tiempo real de una empresa usando su símbolo (ticker).
    """
    engine_bolsa = BolsaEngine()
    return engine_bolsa.obtener_analisis_completo(ticker)

# --- CONFIGURACIÓN DE FASTAPI ---
app = FastAPI(
    title="Daiko AI Engine Private",
    description="Backend central para gestión de IA y análisis financiero",
    version="2.0",
    lifespan=lifespan # Añadimos el ciclo de vida aquí
)

# --- TRAMPA DE ERRORES GLOBALES (NUEVO) ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"¡ERROR FATAL EN LA RUTA: {request.url.path}!")
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "error": "Error interno del servidor", 
            "detalle_exacto": str(exc)
        }
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registramos el router de IA con el prefijo /ai una sola vez
app.include_router(ai_router, prefix="/ai")

# Ruta principal requerida por Render para verificar salud (200 OK)
@app.get("/")
def health_check():
    return {
        "status": "online", 
        "engine": "Daiko 2.0", 
        "owner": "Kevin Guevara",
        "database": "connected and synced",
        "modules": ["BolsaEngine", "AI_Routes"]
    }
