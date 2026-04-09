import json
import os
from datetime import datetime # Importante para el tiempo
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import google.generativeai as genai
from dotenv import load_dotenv

# --- IMPORTACIONES DE TU PROYECTO ---
from database import get_db
from models import User, AIChatHistory, Transaction

# 1. CARGAR CONFIGURACIÓN
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# 2. CONFIGURAR EL MODELO DE IA
model = genai.GenerativeModel('gemini-1.5-flash') 

# 3. DEFINIR EL ROUTER
router = APIRouter(prefix="/ai", tags=["IA (Daiko)"])

# --- EL PROMPT MAESTRO DE DAIKO ---
CONTEXTO_DAIKO = """
ROLE:
You are DAIKO (Active Intelligence), the premier financial digital assistant for the 'Finara' ecosystem. 
Your goal is to provide high-level financial education, technical analysis, and saving strategies.

STRICT GUARDRAILS:
1. FINANCIAL SCOPE ONLY.
2. NO INVESTMENT ADVICE.
3. ALWAYS output a valid JSON object.

JSON SCHEMA STRUCTURE:
{
  "text": "Respuesta detallada en español.",
  "type": "text" | "analysis",
  "trend": "string" | null,
  "rsiLevel": "string" | null
}
"""

@router.get("/consultar")
async def consultar(
    pregunta: str, 
    db: Session = Depends(get_db)
):
    print("--- INICIANDO DAIKO (CONTROL DE SALUDO) ---")
    
    # 1. BUSCAR USUARIO
    user = db.query(User).filter(User.id == 39).first()
    if not user:
        return {"text": "Usuario no encontrado.", "type": "text"}

    # 2. CONTEXTO DE GASTOS
    resumen_gastos = ""
    try:
        gastos = db.query(Transaction).filter(Transaction.user_id == user.id).limit(5).all()
        resumen_gastos = "\n".join([f"- {g.description}: ${g.amount}" for g in gastos]) if gastos else "Sin gastos."
    except:
        resumen_gastos = "Error al leer gastos."

    # --- LÓGICA DE SALUDO DINÁMICO ---
    conteo_chats = db.query(AIChatHistory).filter(AIChatHistory.user_id == user.id).count()
    
    if conteo_chats > 0:
        regla_saludo = "IMPORTANT: This is NOT the first message. DO NOT say '¡Hola! Soy Daiko'. Answer directly in Spanish."
    else:
        regla_saludo = "FIRST MESSAGE: You MUST start your response with '¡Hola! Soy Daiko'."

    # 3. LLAMADA A GEMINI
    try:
        prompt_final = (
            f"{CONTEXTO_DAIKO}\n\n"
            f"INSTRUCTION: {regla_saludo}\n\n"
            f"CONTEXTO GASTOS USUARIO:\n{resumen_gastos}\n\n"
            f"PREGUNTA DEL USUARIO: {pregunta}"
        )
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        resultado = json.loads(response.text)

        # 4. GUARDAR EN HISTORIAL (CORREGIDO)
        try:
            nuevo_chat = AIChatHistory(
                user_id=user.id,
                user_message=pregunta,
                ai_response=resultado
                # NO ponemos created_at para que la DB use su default y no falle
            )
            db.add(nuevo_chat)
            db.commit()
        except Exception as e_db:
            db.rollback()
            print(f"Error guardando historial: {e_db}")

        return resultado

    except Exception as e:
        return {"text": f"Error en Daiko: {str(e)}", "type": "text"}

@router.get("/historial")
async def ver_historial(db: Session = Depends(get_db)):
    try:
        chats = db.query(AIChatHistory).filter(
            AIChatHistory.user_id == 39
        ).order_by(AIChatHistory.created_at.desc()).limit(10).all()
        return chats
    except Exception as e:
        return {"error": str(e)}
