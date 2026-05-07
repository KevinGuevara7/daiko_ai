import json
import os
import yfinance as yf
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

# --- MOTOR DE ANÁLISIS DE BOLSA ---
def obtener_analisis_bolsa(ticker: str):
    """
    Consulta información financiera y de bolsa en tiempo real de una empresa usando su símbolo (ej: AAPL, NVDA, MSFT).
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty:
            return {"error": f"No se encontraron datos para el símbolo {ticker}."}
        
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
    except Exception as e:
        print(f"Error en Yahoo Finance: {e}")
        return {"error": "Error al conectar con el mercado financiero."}

# --- CONFIGURACIÓN DEL MODELO ---
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash', # Recomiendo 1.5-flash para mayor estabilidad con tools
    tools=[obtener_analisis_bolsa]
)

router = APIRouter(tags=["Finara AI"])

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
- HERRAMIENTAS: Si el usuario pregunta por precios de acciones, empresas o mercado, USA 'obtener_analisis_bolsa'.
- BREVEDAD: Ve directo al grano sin saludos.
- FORMATO: Tu respuesta final debe ser SIEMPRE un JSON con la clave "text".
"""

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="No hay usuarios en la base de datos")

    if data.contexto_gastos:
        resumen_gastos = "\n".join([f"- {g.get('item', 'Item')}: ${g.get('valor', 0)}" for g in data.contexto_gastos])
        contexto_actual = f"DATOS DE GASTOS ACTUALES DEL USUARIO:\n{resumen_gastos}"
    else:
        contexto_actual = "El usuario no tiene gastos registrados en esta consulta."

    try:
        # Iniciamos chat con herramientas automáticas
        chat = model.start_chat(enable_automatic_function_calling=True)
        
        prompt_final = f"{CONTEXTO_DAIKO}\n\n{contexto_actual}\n\nPregunta: {data.pregunta}"
        
        # Quitamos la restricción de MIME TYPE aquí para que Gemini pueda usar la tool libremente
        # y luego procesamos el texto a JSON manualmente
        response = chat.send_message(prompt_final)
        
        # Intento de parsear JSON, si falla, creamos el esquema manualmente
        try:
            # Limpiamos posibles caracteres extraños de la respuesta de Gemini
            texto_limpio = response.text.replace('```json', '').replace('```', '').strip()
            resultado = json.loads(texto_limpio)
            if "text" not in resultado:
                resultado = {"text": response.text}
        except:
            resultado = {"text": response.text}

        # Guardado en DB
        es_nuevo = db.query(AIChatHistory).filter(AIChatHistory.session_id == data.session_id).count() == 0
        titulo_chat = data.pregunta[:30] + "..." if es_nuevo else None

        nuevo_registro = AIChatHistory(
            user_id=user.id, 
            session_id=data.session_id, 
            session_title=titulo_chat,
            user_message=data.pregunta, 
            ai_response=resultado 
        )
        db.add(nuevo_registro)
        db.commit()

        return resultado

    except Exception as e:
        print(f"DEBUG ERROR DAIKO: {str(e)}")
        return {"text": f"Error en procesamiento: {str(e)[:50]}"}

# --- (Endpoints de sesiones y historial se mantienen igual) ---
@router.get("/sessions")
async def listar_sesiones(db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    if not user: return []
    
    sesiones = db.query(
        AIChatHistory.session_id, 
        AIChatHistory.session_title, 
        func.max(AIChatHistory.created_at).label("ultima_vez")
    ).filter(AIChatHistory.user_id == user.id)\
     .group_by(AIChatHistory.session_id, AIChatHistory.session_title)\
     .order_by(text("ultima_vez DESC")).all()
    
    return [
        {
            "session_id": s.session_id, 
            "title": s.session_title or "Conversación", 
            "ultima_vez": s.ultima_vez.isoformat()
        } for s in sesiones
    ]

@router.get("/historial/{session_id}")
async def ver_historial_sesion(session_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    registros = db.query(AIChatHistory).filter(
        AIChatHistory.user_id == user.id, 
        AIChatHistory.session_id == session_id
    ).order_by(AIChatHistory.created_at.asc()).all()
    
    return [
        {
            "user_message": r.user_message, 
            "ai_response": r.ai_response["text"] if isinstance(r.ai_response, dict) else r.ai_response, 
            "created_at": r.created_at.isoformat()
        } for r in registros
    ]