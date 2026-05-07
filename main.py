import yfinance as yf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ai_routes import router as ai_router

# Importaciones de Base de Datos
from database import engine, Base
import models 

# --- INICIALIZACIÓN DE BASE DE DATOS ---
Base.metadata.create_all(bind=engine)

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
    version="2.0"
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

@app.get("/")
def health_check():
    return {
        "status": "online", 
        "engine": "Daiko 2.0", 
        "owner": "Kevin Guevara",
        "database": "connected and synced",
        "modules": ["BolsaEngine", "AI_Routes"]
    }