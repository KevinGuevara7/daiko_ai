import json
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import google.generativeai as genai
from dotenv import load_dotenv

# --- IMPORTACIONES DE TU PROYECTO ---
from database import get_db
from models import User, AIChatHistory, Transaction
# from auth import verify_token, oauth2_scheme  # Comentado para bypass

# 1. CARGAR CONFIGURACIÓN
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# 2. CONFIGURAR EL MODELO DE IA
model = genai.GenerativeModel('gemini-2.0-flash') 

# 3. DEFINIR EL ROUTER (Crucial para evitar el NameError)
router = APIRouter(prefix="/ai", tags=["IA (Daiko)"])

# --- EL PROMPT MAESTRO DE DAIKO ---
CONTEXTO_DAIKO = """
ROLE:
You are DAIKO (Active Intelligence), the premier financial digital assistant for the 'Finara' ecosystem. 
Your goal is to provide high-level financial education, technical analysis, and saving strategies.

PERSONALITY & TONE:
- Professional, encouraging, and strictly objective.
- Always start the very first interaction of a session with: "¡Hola! Soy Daiko".
- Language: You MUST process the logic in English but provide the 'text' field content in SPANISH.

STRICT GUARDRAILS:
1. FINANCIAL SCOPE ONLY. If asked about other topics, politely decline.
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
    print("--- RECONECTANDO DAIKO CON PROTECCIÓN (ID 39) ---")
    
    # 1. BUSCAR USUARIO (Si esto falla, el JSON te avisará)
    try:
        user = db.query(User).filter(User.id == 39).first()
        if not user:
            return {"text": "Error: Usuario 39 no encontrado en DB.", "type": "text"}
    except Exception as e:
        return {"text": f"Error de conexión a DB: {str(e)}", "type": "text"}

    # 2. INTENTAR LEER GASTOS (Si falla, Daiko sigue vivo)
    resumen_gastos = "No se pudo acceder a los gastos por error de conexión."
    try:
        gastos = db.query(Transaction).filter(Transaction.user_id == user.id).limit(5).all()
        if gastos:
            resumen_gastos = "\n".join([f"- {g.description}: ${g.amount}" for g in gastos])
        else:
            resumen_gastos = "El usuario no tiene gastos registrados."
    except Exception as e:
        print(f"Error leyendo gastos: {e}")
        resumen_gastos = "Error al obtener historial de gastos."

    # 3. LLAMADA A GEMINI
    try:
        prompt_final = f"{CONTEXTO_DAIKO}\n\nCONTEXTO GASTOS:\n{resumen_gastos}\n\nPREGUNTA: {pregunta}"
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        resultado = json.loads(response.text)
    except Exception as e:
        return {"text": f"Error en IA: {str(e)}", "type": "text"}

    # 4. INTENTAR GUARDAR (Si falla, igual te damos la respuesta)
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
        print(f"No se guardó el historial en DB: {e}")

    return resultado

@router.get("/historial")
async def ver_historial(
    db: Session = Depends(get_db)
):
    print("--- CONSULTANDO HISTORIAL (BYPASS ID 39) ---")
    try:
        chats = db.query(AIChatHistory).filter(
            AIChatHistory.user_id == 39
        ).order_by(AIChatHistory.created_at.desc()).limit(10).all()
        return chats
    except Exception as e:
        return {"error": str(e)}
