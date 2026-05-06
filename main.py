import yfinance as yf
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ai_routes import router as ai_router

# Importaciones de Base de Datos
from database import engine, Base
import models  # Asegúrate de que models.py esté en el mismo directorio

# --- INICIALIZACIÓN DE BASE DE DATOS ---
# Crea las tablas en Render/PostgreSQL si no existen
Base.metadata.create_all(bind=engine)

# --- MOTOR DE ANÁLISIS DE BOLSA ---
class BolsaEngine:
    """
    Motor de análisis de bolsa independiente para Daiko AI.
    Optimizado para reducir peticiones externas.
    """

    @staticmethod
    def obtener_precio_actual(ticker_simbolo: str):
        """Devuelve el precio de cierre más reciente."""
        ticker = yf.Ticker(ticker_simbolo)
        data = ticker.history(period="1d")
        if data.empty:
            return None
        return round(data['Close'].iloc[-1], 2)

    @staticmethod
    def obtener_analisis_completo(ticker_simbolo: str):
        """
        Extrae datos profundos. Optimizado para realizar 
        una sola llamada a .info.
        """
        ticker = yf.Ticker(ticker_simbolo)
        hist = ticker.history(period="5d")
        
        if hist.empty:
            return {"error": "Símbolo no encontrado o sin datos"}

        # Extraer info una sola vez (es una petición costosa)
        info = ticker.info
        
        precio_actual = hist['Close'].iloc[-1]
        precio_inicial = hist['Close'].iloc[0]
        rendimiento_semanal = ((precio_actual - precio_inicial) / precio_inicial) * 100

        return {
            "simbolo": ticker_simbolo,
            "nombre": info.get('longName', 'N/A'),
            "precio_actual": round(precio_actual, 2),
            "tendencia_semanal_pct": round(rendimiento_semanal, 2),
            "sector": info.get('sector', 'Desconocido'),
            "resumen": info.get('longBusinessSummary', 'Sin descripción')[:200] + "..."
        }

# --- CONFIGURACIÓN DE FASTAPI ---
app = FastAPI(
    title="Daiko AI Engine Private",
    description="Backend central para gestión de IA y análisis financiero",
    version="2.0"
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En producción, cambia esto por la URL de tu app
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- RUTAS ---
# Incluimos las rutas de la IA (mensajería, lógica de Gemini, etc.)
app.include_router(ai_router)

@app.get("/")
def health_check():
    """Endpoint para verificar el estado del servicio en Render"""
    return {
        "status": "online", 
        "engine": "Daiko 2.0", 
        "owner": "Kevin Guevara",
        "database": "connected and synced",
        "modules": ["BolsaEngine", "AI_Routes"]
    }