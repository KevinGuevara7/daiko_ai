import json
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import google.generativeai as genai
from dotenv import load_dotenv

# --- IMPORTACIONES DE TU PROYECTO ---
from database import get_db
from models import User, AIUsageStats, AIChatHistory, Transaction
from auth import verify_token, oauth2_scheme

# 1. CARGAR CONFIGURACIÓN
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# 2. CONFIGURAR EL MODELO DE IA
model = genai.GenerativeModel('gemini-2.0-flash') 

# 3. DEFINIR RUTAS (ROUTER)
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
    db: Session = Depends(get_db), 
    token: str = Depends(oauth2_scheme)
):
    try:
        # A. IDENTIFICAR USUARIO POR EL TOKEN
        data = verify_token(token)
        user = db.query(User).filter(User.email == data["sub"]).first()
        if not user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")

        # B. VERIFICAR LÍMITE DE TOKENS (Uso de tu tabla ai_usage_stats)
        stats = db.query(AIUsageStats).filter(AIUsageStats.user_id == user.id).first()
        if not stats:
            # Si por alguna razón no existe, lo creamos
            stats = AIUsageStats(user_id=user.id)
            db.add(stats)
            db.commit()

        if stats.daily_tokens_count >= stats.daily_limit:
            return {
                "text": "¡Hola! Soy Daiko. Has alcanzado tu límite de 50 consultas diarias. ¡Nos vemos mañana para seguir mejorando tus finanzas!",
                "type": "text"
            }

        # C. OBTENER CONTEXTO REAL (Últimos 5 gastos del usuario)
        gastos = db.query(Transaction).filter(Transaction.user_id == user.id).limit(5).all()
        resumen_gastos = "\n".join([f"- {g.description}: ${g.amount}" for g in gastos])

        # D. LLAMADA A GEMINI
        prompt_final = f"{CONTEXTO_DAIKO}\n\nCONTEXTO GASTOS USUARIO:\n{resumen_gastos}\n\nPREGUNTA USUARIO: {pregunta}"
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )

        resultado = json.loads(response.text)

        # E. ACTUALIZAR BASE DE DATOS (Historial y Tokens)
        # 1. Guardar en el historial
        nuevo_chat = AIChatHistory(
            user_id=user.id,
            user_message=pregunta,
            ai_response=resultado
        )
        # 2. Sumar token usado
        stats.daily_tokens_count += 1
        
        db.add(nuevo_chat)
        db.commit()

        return resultado 

    except Exception as e:
        db.rollback() # Si algo falla, deshacemos cambios en DB
        print(f"Error en Daiko: {e}")
        raise HTTPException(status_code=500, detail="Error interno de Daiko")

@router.get("/historial")
async def ver_historial(
    db: Session = Depends(get_db), 
    token: str = Depends(oauth2_scheme)
):
    data = verify_token(token)
    user = db.query(User).filter(User.email == data["sub"]).first()
    
    # Validación de seguridad extra
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    chats = db.query(AIChatHistory).filter(
        AIChatHistory.user_id == user.id
    ).order_by(AIChatHistory.created_at.desc()).limit(10).all()
    
    return chats