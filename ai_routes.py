import json
import os
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
import google.generativeai as genai
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv

# --- IMPORTACIONES PROPIAS ---
from database import get_db
from models import User, AIChatHistory, Transaction
from auth import verify_token 

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash') 

router = APIRouter(prefix="/ai", tags=["IA (Daiko)"])

# 1. DEFINICIÓN DEL MODELO DE ENTRADA (Para recibir el JSON de Flutter)
class ConsultaChat(BaseModel):
    pregunta: str
    historial: List[dict]
    contexto_gastos: List[dict]
    user_name: Optional[str] = "Kevin"

CONTEXTO_DAIKO = """
ROLE: Eres DAIKO, el núcleo de inteligencia financiera de la app Finara. Tu usuario es Kevin.
PERSONALITY: Eres un analista contable senior, directo, profesional y motivador.
STRICT RULE: Responde directamente en español. 
NO te presentes, NO digas 'Hola', NO digas 'Muy bien Kevin' en cada mensaje. 
Si el usuario pregunta sobre sus gastos, usa los datos proporcionados en el contexto.
Si pregunta algo fuera de finanzas, recuérdale que eres su asistente contable.
ALWAYS output a valid JSON object with a "text" field.
"""

@router.post("/consultar")
async def consultar(
    data: ConsultaChat, 
    db: Session = Depends(get_db), 
    token_data: dict = Depends(verify_token)
):
    # 2. IDENTIFICAR AL USUARIO
    user_email = token_data.get("sub")
    user = db.query(User).filter(User.email == user_email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # 3. PROCESAR MEMORIA DEL CHAT (Historial enviado desde Flutter)
    memoria_texto = ""
    for h in data.historial:
        role = "Usuario" if h["role"] == "user" else "Daiko"
        memoria_texto += f"{role}: {h['content']}\n"

    # 4. PROCESAR CONTEXTO DE GASTOS (Datos Mock/Reales enviados desde Flutter)
    resumen_gastos = "\n".join([
        f"- {g.get('item', 'Gasto')}: ${g.get('valor', 0)} (Cat: {g.get('cat', 'Varios')})" 
        for g in data.contexto_gastos
    ])

    # 5. LLAMADA A GEMINI CON CONTEXTO COMPLETO
    try:
        prompt_final = f"""
        {CONTEXTO_DAIKO}
        
        SITUACIÓN FINANCIERA ACTUAL (Gastos detectados):
        {resumen_gastos}

        MEMORIA DE LA CONVERSACIÓN PREVIA:
        {memoria_texto}
        
        NUEVA PREGUNTA DE KEVIN:
        {data.pregunta}
        """
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        
        resultado = json.loads(response.text)

        # 6. GUARDAR EN LA BASE DE DATOS PARA EL HISTORIAL DE LA APP
        try:
            nuevo_chat = AIChatHistory(
                user_id=user.id,
                user_message=data.pregunta,
                ai_response=resultado 
            )
            db.add(nuevo_chat)
            db.commit()
        except Exception as e_db:
            db.rollback()
            print(f"Error guardando historial en DB: {e_db}")

        return resultado

    except Exception as e:
        print(f"Error en el motor Gemini: {e}")
        return {
            "text": "Lo siento Kevin, Daiko tiene un pequeño error de conexión. Intenta de nuevo.", 
            "type": "error"
        }

@router.get("/historial")
async def ver_historial(
    db: Session = Depends(get_db), 
    token_data: dict = Depends(verify_token)
):
    user_email = token_data.get("sub")
    user = db.query(User).filter(User.email == user_email).first()
    
    registros = db.query(AIChatHistory).filter(
        AIChatHistory.user_id == user.id
    ).order_by(AIChatHistory.created_at.desc()).limit(20).all()

    return [
        {
            "user_message": r.user_message,
            "ai_response": r.ai_response["text"] if isinstance(r.ai_response, dict) else r.ai_response,
            "created_at": r.created_at
        } for r in registros
    ]
