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

router = APIRouter(prefix="/ai", tags=["IA (Daiko)"])

# 1. MODELO ACTUALIZADO: Ahora recibe el session_id desde Flutter
class ConsultaChat(BaseModel):
    pregunta: str
    session_id: str  # <--- CRÍTICO: Para que no sea NULL en la DB
    historial: List[dict]
    contexto_gastos: List[dict]
    user_name: Optional[str] = "Kevin"

CONTEXTO_DAIKO = """
ROLE: Eres DAIKO, el núcleo de inteligencia financiera de la app Finara. Tu usuario es Kevin.
STRICT RULE: Responde directamente en español. 
NO te presentes, NO digas 'Hola'. 
Usa los datos de gastos para dar consejos de ahorro y gestión.
ALWAYS output a valid JSON object with a "text" field.
"""

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    # Buscamos a Kevin o al primer usuario
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="No hay usuarios en la base de datos")

    # Formatear memoria para Gemini
    memoria_texto = ""
    for h in data.historial:
        role = "Usuario" if h["role"] == "user" else "Daiko"
        memoria_texto += f"{role}: {h['content']}\n"

    # Formatear gastos para Gemini
    resumen_gastos = "\n".join([
        f"- {g.get('item', 'Gasto')}: ${g.get('valor', 0)}" for g in data.contexto_gastos
    ])

    try:
        # Prompt con toda la carga de datos
        prompt_final = f"{CONTEXTO_DAIKO}\nGastos Recientes:\n{resumen_gastos}\nHistorial de esta sesión:\n{memoria_texto}\nPregunta actual: {data.pregunta}"
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        
        resultado = json.loads(response.text)

        # --- LÓGICA DE TÍTULO AUTOMÁTICO ---
        # Si es el primer mensaje de la sesión, creamos un título corto
        es_nuevo = db.query(AIChatHistory).filter(AIChatHistory.session_id == data.session_id).count() == 0
        titulo_chat = data.pregunta[:25] + "..." if es_nuevo else None

        # 2. GUARDADO CORREGIDO: Ya no habrá NULLs
        nuevo_chat = AIChatHistory(
            user_id=user.id, 
            session_id=data.session_id, 
            session_title=titulo_chat, # Se guarda solo si es nuevo, si no, la DB mantiene el anterior
            user_message=data.pregunta, 
            ai_response=resultado
        )
        
        db.add(nuevo_chat)
        db.commit()

        return resultado

    except Exception as e:
        print(f"Error en Daiko: {e}")
        return {"text": f"Error técnico: {str(e)}"}

# 3. NUEVO ENDPOINT: Para que Flutter vea los chats en el menú lateral
@router.get("/sessions")
async def listar_sesiones(db: Session = Depends(get_db)):
    # Buscamos al usuario Kevin para traer sus sesiones
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    
    if not user:
        return []

    # Consultamos sesiones únicas ordenadas por la más reciente
    sesiones = db.query(
        AIChatHistory.session_id,
        AIChatHistory.session_title,
        func.max(AIChatHistory.created_at).label("ultima_vez")
    ).filter(AIChatHistory.user_id == user.id).group_by(
        AIChatHistory.session_id, 
        AIChatHistory.session_title
    ).order_by(text("ultima_vez DESC")).all()

    return [
        {
            "session_id": s.session_id, 
            "title": s.session_title or "Chat antiguo", 
            "ultima_vez": s.ultima_vez.isoformat()
        } for s in sesiones
    ]
