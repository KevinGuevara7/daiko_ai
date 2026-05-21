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
    """Consulta información financiera en tiempo real usando el símbolo."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty:
            return {"error": f"No se encontraron datos para {ticker}."}

        info = stock.info
        precio_actual = float(hist["Close"].iloc[-1])
        precio_inicial = float(hist["Close"].iloc[0])
        rendimiento = ((precio_actual - precio_inicial) / precio_inicial) * 100

        return {
            "nombre": info.get("longName", ticker),
            "precio": round(precio_actual, 2),
            "cambio_semanal": f"{round(rendimiento, 2)}%",
            "sector": info.get("sector", "N/A"),
            "resumen": (info.get("longBusinessSummary", "")[:150] + "...")
        }
    except Exception as e:
        print(f"Error en Yahoo Finance: {e}")
        return {"error": "Error al conectar con el mercado."}

# --- CONFIGURACIÓN DEL MODELO ---
model = genai.GenerativeModel(model_name="gemini-1.5-flash")
router = APIRouter(tags=["Finara AI"])

# --- ESQUEMA DE DATOS ---
class ConsultaChat(BaseModel):
    pregunta: str
    session_id: str
    historial: List[dict] = []
    contexto_gastos: List[dict] = []
    user_name: Optional[str] = "Kevin"
    tool: Optional[str] = "rápido"

# --- PROMPT ---
CONTEXTO_DAIKO = """
### SYSTEM_ROLE
DAIKO: Inteligencia analítica de Finara. Especialista en finanzas.
### RULES
- Responde siempre en español.
- Si analizas bolsa o gastos, sé técnico y detallado.
- Tu respuesta final debe ser SIEMPRE un JSON con la clave 'text'.
"""

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # --- contexto gastos ---
    contexto_actual = "Sin gastos registrados."
    if data.contexto_gastos:
        resumen_gastos = "\n".join([f"- {g.get('item', 'Item')}: ${g.get('valor', 0)}" for g in data.contexto_gastos])
        contexto_actual = f"GASTOS:\n{resumen_gastos}"

    # --- modo ---
    instrucciones_tool = {
        "bolsa": "MODO BOLSA: Analiza la empresa proporcionada.",
        "pensar": "MODO PENSAR: Análisis financiero profundo.",
        "gastos": "MODO GASTOS: Detecta fugas de dinero.",
    }.get(data.tool, "MODO RÁPIDO: Sé conciso.")

    # --- lógica bolsa ---
    contexto_bolsa = ""
    if data.tool == "bolsa":
        palabras = data.pregunta.upper().split()
        ticker = next((p for p in palabras if len(p) <= 5), None)
        if ticker:
            datos = obtener_analisis_bolsa(ticker)
            contexto_bolsa = f"\nDATOS BOLSA: {json.dumps(datos)}"

    # --- LLAMADA A GEMINI ---
    try:
        prompt_final = f"{CONTEXTO_DAIKO}\n{instrucciones_tool}\n{contexto_actual}\n{contexto_bolsa}\n\nPregunta: {data.pregunta}"
        response = model.generate_content(prompt_final)
        
        texto_limpio = response.text.replace("```json", "").replace("```", "").strip()
        
        try:
            resultado = json.loads(texto_limpio)
            if "text" not in resultado: resultado = {"text": texto_limpio}
        except:
            resultado = {"text": texto_limpio}

        # --- DB ---
        es_nuevo = db.query(AIChatHistory).filter(AIChatHistory.session_id == data.session_id).count() == 0
        titulo = data.pregunta[:30] + "..." if es_nuevo else None

        db.add(AIChatHistory(user_id=user.id, session_id=data.session_id, session_title=titulo, user_message=data.pregunta, ai_response=resultado))
        db.commit()

        return resultado
    except Exception as e:
        print(f"ERROR DAIKO: {str(e)}")
        return {"text": "Error al procesar la solicitud."}

# --- SESIONES E HISTORIAL ---
@router.get("/sessions")
async def listar_sesiones(db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    if not user: return []
    
    sesiones = db.query(AIChatHistory.session_id, AIChatHistory.session_title, func.max(AIChatHistory.created_at).label("ultima_vez"))\
                 .filter(AIChatHistory.user_id == user.id)\
                 .group_by(AIChatHistory.session_id, AIChatHistory.session_title)\
                 .order_by(text("ultima_vez DESC")).all()
    
    return [{"session_id": s.session_id, "title": s.session_title or "Conversación", "ultima_vez": s.ultima_vez.isoformat()} for s in sesiones]

@router.get("/historial/{session_id}")
async def ver_historial_sesion(session_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    regs = db.query(AIChatHistory).filter(AIChatHistory.user_id == user.id, AIChatHistory.session_id == session_id).order_by(AIChatHistory.created_at.asc()).all()
    return [{"user_message": r.user_message, "ai_response": r.ai_response.get("text", r.ai_response) if isinstance(r.ai_response, dict) else r.ai_response, "created_at": r.created_at.isoformat()} for r in regs]