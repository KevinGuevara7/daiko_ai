import json
import os
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
model = genai.GenerativeModel('gemini-2.5-flash') 

# 3. DEFINIR EL ROUTER
router = APIRouter(prefix="/ai", tags=["IA (Daiko)"])

# --- EL PROMPT MAESTRO DE DAIKO (MODIFICADO) ---
CONTEXTO_DAIKO = """
ROLE:
You are DAIKO (Active Intelligence), the premier financial digital assistant for the 'Finara' ecosystem. 
Your goal is to provide high-level financial education, technical analysis, and saving strategies.

PERSONALITY & TONE:
- Professional, encouraging, and strictly objective.
- INTRODUCTION RULE:
  * If the CHAT_HISTORY provided below is EMPTY or says 'First interaction', you MUST start with: "¡Hola! Soy Daiko".
  * If the CHAT_HISTORY has previous messages, DO NOT say "¡Hola! Soy Daiko". Go straight to the answer.
- Language: You MUST process the logic in English but provide the 'text' field content in SPANISH.

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
    print("--- INICIANDO DAIKO CON MEMORIA (ID 39) ---")
    
    # 1. BUSCAR USUARIO
    try:
        user = db.query(User).filter(User.id == 39).first()
        if not user:
            return {"text": "Error: Usuario 39 no encontrado.", "type": "text"}
    except Exception as e:
        return {"text": f"Error de conexión a DB: {str(e)}", "type": "text"}

    # 2. INTENTAR LEER GASTOS
    resumen_gastos = ""
    try:
        gastos = db.query(Transaction).filter(Transaction.user_id == user.id).limit(5).all()
        if gastos:
            resumen_gastos = "\n".join([f"- {g.description}: ${g.amount}" for g in gastos])
        else:
            resumen_gastos = "El usuario no tiene gastos registrados."
    except Exception as e:
        resumen_gastos = "No se pudo obtener el contexto de gastos."

    # --- NUEVA LÓGICA: MEMORIA PARA EL SALUDO ---
    texto_historial = "First interaction"
    try:
        # Buscamos los últimos 3 chats para que sepa si ya se saludaron
        historial_previo = db.query(AIChatHistory).filter(
            AIChatHistory.user_id == user.id
        ).order_by(AIChatHistory.created_at.desc()).limit(3).all()
        
        if historial_previo:
            mensajes = []
            for h in reversed(historial_previo):
                # Intentamos extraer el texto de la respuesta guardada
                resp_text = h.ai_response.get('text', '') if isinstance(h.ai_response, dict) else str(h.ai_response)
                mensajes.append(f"User: {h.user_message}\nDaiko: {resp_text}")
            texto_historial = "\n".join(mensajes)
    except Exception as e:
        print(f"Error cargando historial para memoria: {e}")

    # 3. LLAMADA A GEMINI
    try:
        prompt_final = (
            f"{CONTEXTO_DAIKO}\n\n"
            f"CHAT_HISTORY:\n{texto_historial}\n\n"
            f"CONTEXTO GASTOS:\n{resumen_gastos}\n\n"
            f"PREGUNTA ACTUAL: {pregunta}"
        )
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        resultado = json.loads(response.text)
    except Exception as e:
        return {"text": f"Error en IA: {str(e)}", "type": "text"}

    # 4. GUARDAR EN HISTORIAL
    try:
        nuevo_chat = AIChatHistory(
            user_id=user.id,
            user_message=pregunta,
            ai_response=resultado
        )
        db.add(nuevo_chat)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error al guardar: {e}")

    return resultado

@router.get("/historial")
async def ver_historial(db: Session = Depends(get_db)):
    try:
        chats = db.query(AIChatHistory).filter(
            AIChatHistory.user_id == 39
        ).order_by(AIChatHistory.created_at.desc()).limit(10).all()
        return chats
    except Exception as e:
        return {"error": str(e)}
