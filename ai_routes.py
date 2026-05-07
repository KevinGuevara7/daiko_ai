import json
import os
import yfinance as yf # Importante para que funcione el motor
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, text
import google.generativeai as genai
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv

# --- IMPORTACIONES PROPIAS ---
from database import get_db
from models import User, AIChatHistory

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# --- MOTOR DE ANÁLISIS DE BOLSA (Integrado para evitar errores de importación) ---
def obtener_analisis_bolsa(ticker: str):
    """
    Consulta información financiera y de bolsa en tiempo real de una empresa usando su símbolo (ej: AAPL, NVDA, MSFT).
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty:
            return {"error": "No se encontraron datos para ese símbolo."}
        
        info = stock.info
        precio_actual = hist['Close'].iloc[-1]
        precio_inicial = hist['Close'].iloc[0]
        rendimiento = ((precio_actual - precio_inicial) / precio_inicial) * 100

        return {
            "nombre": info.get('longName', ticker),
            "precio": round(precio_actual, 2),
            "cambio_semanal": f"{round(rendimiento, 2)}%",
            "sector": info.get('sector', 'N/A'),
            "resumen": info.get('longBusinessSummary', '')[:150] + "..."
        }
    except Exception:
        return {"error": "Error al conectar con el mercado financiero."}

# --- CONFIGURACIÓN DEL MODELO CON TOOLS ---
model = genai.GenerativeModel(
    model_name='gemini-2.0-flash', # Actualizado a tu versión
    tools=[obtener_analisis_bolsa] # <--- AQUÍ ESTÁ LA MAGIA
)

router = APIRouter(prefix="/ai", tags=["Finara AI"])

class ConsultaChat(BaseModel):
    pregunta: str
    session_id: str 
    historial: List[dict]
    contexto_gastos: List[dict]
    user_name: Optional[str] = "Kevin"

CONTEXTO_DAIKO = """
### SYSTEM_ROLE
DAIKO: Inteligencia analítica de Finara. Especialista en optimización de flujo de caja y estrategia financiera.

### OPERATIONAL_RULES
- IDIOMA: Español.
- HERRAMIENTAS: Tienes acceso a 'obtener_analisis_bolsa'. Si preguntan por acciones o empresas, úsala.
- BREVEDAD: Prohibido saludos. Ve directo al grano.
- FORMATO: Output estrictamente JSON: {"text": "mensaje"}.
"""

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="No hay usuarios")

    # --- LÓGICA DE GASTOS ---
    if data.contexto_gastos:
        resumen_gastos = "\n".join([f"- {g.get('item')}: ${g.get('valor')}" for g in data.contexto_gastos])
        contexto_actual = f"DATOS REALES DE GASTOS:\n{resumen_gastos}"
    else:
        contexto_actual = "El usuario no tiene gastos registrados hoy."

    try:
        # Iniciamos chat con llamado automático de funciones habilitado
        chat = model.start_chat(enable_automatic_function_calling=True)
        
        prompt_final = f"{CONTEXTO_DAIKO}\n\n{contexto_actual}\n\nPregunta: {data.pregunta}"
        
        response = chat.send_message(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        
        resultado = json.loads(response.text)

        # Guardar en base de datos
        nuevo_chat = AIChatHistory(
            user_id=user.id, 
            session_id=data.session_id, 
            user_message=data.pregunta, 
            ai_response=resultado
        )
        db.add(nuevo_chat)
        db.commit()

        return resultado

    except Exception as e:
        print(f"Error en Daiko: {e}")
        return {"text": "Daiko está recalibrando sus algoritmos financieros. Intenta de nuevo."}

# (Los demás endpoints de historial se mantienen igual abajo...)