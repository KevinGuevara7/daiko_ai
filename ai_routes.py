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
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty:
            return {"error": f"No hay datos para {ticker}"}
        info = stock.info
        actual = hist['Close'].iloc[-1]
        inicial = hist['Close'].iloc[0]
        rendimiento = ((actual - inicial) / inicial) * 100
        return {
            "nombre": info.get('longName', ticker),
            "precio": round(actual, 2),
            "cambio": f"{round(rendimiento, 2)}%",
            "sector": info.get('sector', 'N/A')
        }
    except Exception:
        return {"error": "Error de mercado"}

# --- CONFIGURACIÓN DEL MODELO ---
CONTEXTO = "DAIKO: Inteligencia analítica de Finara. Responde siempre en JSON con la clave 'text'."

model = genai.GenerativeModel(
    model_name='gemini-2.5-flash', # Recomiendo 1.5-flash para mayor estabilidad con tools
    tools=[obtener_analisis_bolsa]
)

router = APIRouter(tags=["Finara AI"])

class ConsultaChat(BaseModel):
    pregunta: str
    session_id: str 
    historial: List[dict]
    contexto_gastos: List[dict]
    user_name: Optional[str] = "Kevin"

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    try:
        # 1. Formateo de historial para Gemini
        h_gemini = []
        for m in data.historial:
            role = "user" if m.get("role") == "user" else "model"
            h_gemini.append({"role": role, "parts": [m.get("text", "")]})

        # 2. Inicio de chat con memoria
        chat = model.start_chat(history=h_gemini, enable_automatic_function_calling=True)
        
        # 3. Envío de mensaje
        res = chat.send_message(data.pregunta)
        
        # 4. Limpieza de respuesta (Sintaxis ultra-segura)
        t_raw = res.text
        t_clean = t_raw.strip()
        
        # Eliminamos marcadores de markdown si existen sin usar comillas complejas
        if t_clean.startswith("```"):
            t_clean = t_clean.split("json")[-1].split("\n```")[0].strip()
        
        try:
            resultado = json.loads(t_clean)
        except Exception:
            resultado = {"text": t_raw}

        # 5. Guardado en Base de Datos
        es_nuevo = db.query(AIChatHistory).filter(AIChatHistory.session_id == data.session_id).count() == 0
        nuevo = AIChatHistory(
            user_id=user.id, 
            session_id=data.session_id, 
            session_title=data.pregunta[:30] if es_nuevo else None,
            user_message=data.pregunta, 
            ai_response=resultado 
        )
        db.add(nuevo)
        db.commit()
        
        return resultado

    except Exception as e:
        print(f"Error: {e}")
        return {"text": "Error en el servidor"}

@router.get("/sessions")
async def listar_sesiones(db: Session = Depends(get_db)):
    sesiones = db.query(AIChatHistory.session_id, AIChatHistory.session_title).distinct().all()
    return [{"session_id": s.session_id, "title": s.session_title or "Chat"} for s in sesiones]

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