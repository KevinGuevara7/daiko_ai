import json
import os
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
model = genai.GenerativeModel('gemini-2.5-flash') 

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
- IDIOMA: Detectar y responder en el idioma del usuario (Español por defecto).
- BREVEDAD: Prohibido saludos o introducciones. Ir directo al grano.
- FORMATO: Output estrictamente JSON: {"text": "mensaje"}.
- FLEXIBILIDAD: Si no hay datos de gastos, actúa como consultor financiero teórico y motiva al usuario a registrar movimientos.
"""

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="No hay usuarios")

    # --- LÓGICA DE GASTOS DINÁMICA ---
    if data.contexto_gastos and len(data.contexto_gastos) > 0:
        resumen_gastos = "\n".join([f"- {g.get('item', 'Gasto')}: ${g.get('valor', 0)}" for g in data.contexto_gastos])
        contexto_actual = f"DATOS REALES DE GASTOS:\n{resumen_gastos}\nInstrucción: Clasifica estos gastos y busca fugas de capital."
    else:
        contexto_actual = "ESTADO: El usuario no tiene gastos registrados hoy. Instrucción: Responde dudas generales de finanzas o da consejos de ahorro preventivo."

    # Memoria de conversación
    memoria_texto = "".join([f"{'Usuario' if h['role'] == 'user' else 'Daiko'}: {h['content']}\n" for h in data.historial])

    try:
        prompt_final = f"{CONTEXTO_DAIKO}\n\n{contexto_actual}\n\nMemoria:\n{memoria_texto}\nPregunta: {data.pregunta}"
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        
        resultado = json.loads(response.text)

        # Guardar historial
        es_nuevo = db.query(AIChatHistory).filter(AIChatHistory.session_id == data.session_id).count() == 0
        titulo_chat = data.pregunta[:25] + "..." if es_nuevo else None

        nuevo_chat = AIChatHistory(
            user_id=user.id, 
            session_id=data.session_id, 
            session_title=titulo_chat,
            user_message=data.pregunta, 
            ai_response=resultado
        )
        db.add(nuevo_chat)
        db.commit()

        return resultado

    except Exception as e:
        print(f"Error: {e}")
        return {"text": "Daiko está recalibrando sus algoritmos. Intenta de nuevo."}

# --- ENDPOINTS DE HISTORIAL (SE MANTIENEN IGUAL) ---
@router.get("/sessions")
async def listar_sesiones(db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    if not user: return []
    sesiones = db.query(AIChatHistory.session_id, AIChatHistory.session_title, func.max(AIChatHistory.created_at).label("ultima_vez")).filter(AIChatHistory.user_id == user.id).group_by(AIChatHistory.session_id, AIChatHistory.session_title).order_by(text("ultima_vez DESC")).all()
    return [{"session_id": s.session_id, "title": s.session_title or "Chat antiguo", "ultima_vez": s.ultima_vez.isoformat()} for s in sesiones]

@router.get("/historial/{session_id}")
async def ver_historial_sesion(session_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    registros = db.query(AIChatHistory).filter(AIChatHistory.user_id == user.id, AIChatHistory.session_id == session_id).order_by(AIChatHistory.created_at.asc()).all()
    return [{"user_message": r.user_message, "ai_response": r.ai_response["text"] if isinstance(r.ai_response, dict) else r.ai_response, "created_at": r.created_at.isoformat()} for r in registros]
