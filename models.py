import json
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import google.generativeai as genai
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List, Optional

# --- IMPORTACIONES PROPIAS ---
from database import get_db
from models import User, AIChatHistory, Transaction
from auth import verify_token 

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash') 

router = APIRouter(prefix="/ai", tags=["IA (Daiko)"])

# --- MODELO DE ENTRADA PARA EL POST ---
class ConsultaChat(BaseModel):
    pregunta: str
    session_id: str  # Campo obligatorio para evitar el NULL
    user_name: Optional[str] = "Kevin"

# Instrucción de sistema ajustada
CONTEXTO_DAIKO = """
ROLE: Eres DAIKO, experto financiero de la app Finara. Tu usuario es Kevin.
STRICT RULE: Responde directamente en español. 
NO te presentes, NO digas 'Hola', NO digas 'Muy bien Kevin'. 
Si el historial muestra que ya saludaste, ve directo al grano.
ALWAYS output a valid JSON object with a "text" field.
"""

@router.post("/consultar") # Cambiado a POST para manejar el cuerpo JSON
async def consultar(
    data: ConsultaChat, 
    db: Session = Depends(get_db), 
    token_data: dict = Depends(verify_token)
):
    # 1. IDENTIFICAR AL USUARIO
    user_email = token_data.get("sub")
    user = db.query(User).filter(User.email == user_email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # 2. OBTENER CONTEXTO DE GASTOS REALES
    gastos = db.query(Transaction).filter(Transaction.user_id == user.id).order_by(Transaction.id.desc()).limit(10).all()
    resumen_gastos = "\n".join([f"- {g.description}: ${g.amount}" for g in gastos])

    # 3. OBTENER MEMORIA POR SESIÓN (Filtramos por session_id para no mezclar chats)
    historial_reciente = db.query(AIChatHistory).filter(
        AIChatHistory.user_id == user.id,
        AIChatHistory.session_id == data.session_id
    ).order_by(AIChatHistory.created_at.desc()).limit(5).all()
    
    historial_reciente.reverse()
    
    memoria_texto = ""
    for h in historial_reciente:
        respuesta_previa = h.ai_response["text"] if isinstance(h.ai_response, dict) else h.ai_response
        memoria_texto += f"Usuario: {h.user_message}\nDaiko: {respuesta_previa}\n"

    # 4. LLAMADA A GEMINI
    try:
        prompt_final = f"""
        {CONTEXTO_DAIKO}
        
        DATOS DE GASTOS DEL USUARIO:
        {resumen_gastos}
        
        HISTORIAL DE ESTA SESIÓN:
        {memoria_texto}
        
        PREGUNTA ACTUAL DE {data.user_name}:
        {data.pregunta}
        """
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        
        resultado = json.loads(response.text)

        # 5. GUARDAR EN LA BASE DE DATOS (Incluyendo session_id)
        try:
            nuevo_chat = AIChatHistory(
                user_id=user.id,
                session_id=data.session_id, # Aquí se asigna el ID recibido de Flutter
                user_message=data.pregunta,
                ai_response=resultado
            )
            db.add(nuevo_chat)
            db.commit()
        except Exception as e_db:
            db.rollback()
            print(f"Error guardando historial: {e_db}")

        return resultado

    except Exception as e:
        print(f"Error Gemini: {e}")
        return {"text": "Lo siento Kevin, Daiko tuvo un error al procesar. Intenta de nuevo.", "type": "error"}

@router.get("/historial/{session_id}") # Endpoint para ver mensajes de una sesión específica
async def ver_historial_sesion(
    session_id: str,
    db: Session = Depends(get_db), 
    token_data: dict = Depends(verify_token)
):
    user_email = token_data.get("sub")
    user = db.query(User).filter(User.email == user_email).first()
    
    registros = db.query(AIChatHistory).filter(
        AIChatHistory.user_id == user.id,
        AIChatHistory.session_id == session_id
    ).order_by(AIChatHistory.created_at.asc()).all()

    return [
        {
            "user_message": r.user_message,
            "ai_response": r.ai_response["text"] if isinstance(r.ai_response, dict) else r.ai_response,
            "created_at": r.created_at
        } for r in registros
    ]

@router.get("/sessions") # Endpoint para listar todas las sesiones en el menú lateral
async def listar_sesiones(
    db: Session = Depends(get_db), 
    token_data: dict = Depends(verify_token)
):
    user_email = token_data.get("sub")
    user = db.query(User).filter(User.email == user_email).first()

    # Agrupamos por session_id para mostrar la lista de chats
    sesiones = db.query(
        AIChatHistory.session_id,
        text("MAX(created_at) as ultima_vez")
    ).filter(AIChatHistory.user_id == user.id).group_by(AIChatHistory.session_id).order_by(text("ultima_vez DESC")).all()

    return [{"session_id": s.session_id, "ultima_vez": s.ultima_vez} for s in sesiones]
