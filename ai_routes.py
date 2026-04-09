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

CONTEXTO_DAIKO = """
ROLE: You are DAIKO. FINANCIAL SCOPE ONLY. 
ALWAYS output a valid JSON object with a "text" field.
"""

@router.get("/consultar")
async def consultar(pregunta: str, db: Session = Depends(get_db)):
    # 1. BUSCAR USUARIO
    user = db.query(User).filter(User.id == 39).first()
    if not user:
        return {"text": "Usuario no encontrado.", "type": "text"}

    # 2. CONTEO PARA SALUDO
    conteo_chats = db.query(AIChatHistory).filter(AIChatHistory.user_id == user.id).count()
    regla_saludo = "DO NOT say 'Hola'" if conteo_chats > 0 else "Start with '¡Hola! Soy Daiko'"

    # 3. LLAMADA A GEMINI
    try:
        prompt_final = f"{CONTEXTO_DAIKO}\nINSTRUCTION: {regla_saludo}\nPREGUNTA: {pregunta}"
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        resultado = json.loads(response.text)

        # 4. GUARDAR EN HISTORIAL (CON DOBLE PROTECCIÓN)
        try:
            # Asegurémonos de que 'resultado' sea un diccionario limpio
            nuevo_chat = AIChatHistory(
                user_id=user.id,
                user_message=pregunta,
                ai_response=resultado # SQLAlchemy debería manejar esto si el modelo es JSON
            )
            db.add(nuevo_chat)
            db.commit()
            print("--- CHAT GUARDADO CON ÉXITO ---")
        except Exception as e_db:
            db.rollback()
            # SEGUNDO INTENTO: Si falla por el tipo de dato, lo guardamos como String
            print(f"Fallo primer intento de guardado: {e_db}")
            try:
                # Forzamos la conversión a String si tu DB es estricta
                nuevo_chat_fallback = AIChatHistory(
                    user_id=user.id,
                    user_message=pregunta,
                    ai_response=json.dumps(resultado) 
                )
                db.add(nuevo_chat_fallback)
                db.commit()
                print("--- CHAT GUARDADO (Fallback String) ---")
            except Exception as e_final:
                db.rollback()
                print(f"ERROR CRÍTICO: Imposible guardar en DB: {e_final}")

        return resultado

    except Exception as e:
        return {"text": f"Error en Daiko: {str(e)}", "type": "text"}

@router.get("/historial")
async def ver_historial(db: Session = Depends(get_db)):
    return db.query(AIChatHistory).filter(AIChatHistory.user_id == 39).all()
