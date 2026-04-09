import json
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import google.generativeai as genai
from dotenv import load_dotenv

# --- IMPORTACIONES DE TU PROYECTO ---
from database import get_db
from models import User, AIChatHistory, Transaction

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash') 
router = APIRouter(prefix="/ai", tags=["IA (Daiko)"])

# --- EL PROMPT MAESTRO DE DAIKO (MODIFICADO PARA SEGURIDAD) ---
CONTEXTO_DAIKO = """
ROLE: You are DAIKO (Active Intelligence), a financial expert.
STRICT RULE: DO NOT introduce yourself. DO NOT say 'Hola, soy Daiko'. 
DO NOT use greetings like '¡Hola!'. 
Start your response IMMEDIATELY with the financial information or answer.
ALWAYS output a valid JSON object with a "text" field.
"""

@router.get("/consultar")
async def consultar(pregunta: str, db: Session = Depends(get_db)):
    # 1. BUSCAR USUARIO (Dejamos el 39 para no romper nada)
    user = db.query(User).filter(User.id == 39).first()
    if not user:
        return {"text": "Usuario no encontrado.", "type": "text"}

    # 2. ELIMINAMOS LA LÓGICA DEL SALUDO DINÁMICO
    # Para que no haya confusión, mandamos una instrucción muda.
    regla_saludo = "Answer directly in Spanish."

    # 3. LLAMADA A GEMINI
    try:
        # Simplificamos el prompt para que Gemini no se confunda
        prompt_final = f"{CONTEXTO_DAIKO}\n\nPREGUNTA: {pregunta}"
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        resultado = json.loads(response.text)

        # 4. INTENTO DE GUARDAR (Lo dejamos igual por si acaso funciona)
        try:
            nuevo_chat = AIChatHistory(
                user_id=user.id,
                user_message=pregunta,
                ai_response=resultado
            )
            db.add(nuevo_chat)
            db.commit()
        except:
            db.rollback() # Si falla, que no haga nada y siga

        return resultado

    except Exception as e:
        # Si Gemini falla (por tokens), devolvemos un mensaje genérico
        return {"text": "Hola, ¿en qué puedo ayudarte con tus finanzas hoy?", "type": "text"}

@router.get("/historial")
async def ver_historial(db: Session = Depends(get_db)):
    return db.query(AIChatHistory).filter(AIChatHistory.user_id == 39).all()
