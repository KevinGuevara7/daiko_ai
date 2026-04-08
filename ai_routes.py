import json
import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import google.generativeai as genai
from dotenv import load_dotenv

# --- IMPORTACIONES DE TU PROYECTO ---
from database import get_db
from models import User, AIUsageStats, AIChatHistory, Transaction
# from auth import verify_token, oauth2_scheme # COMENTADO PARA BYPASS

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
    db: Session = Depends(get_db)
    # token: str = Depends(oauth2_scheme) <-- ELIMINADO PARA BYPASS
):
    print("--- INICIANDO MODO BYPASS ---")
    
    # A. FORZAR USUARIO (Bypass de Token usando ID 39)
    user = db.query(User).filter(User.id == 39).first()
    if not user:
        raise HTTPException(
            status_code=404, 
            detail="MODO BYPASS: No existe el usuario ID 39 en la base de datos."
        )

    # B. LÓGICA DE BASE DE DATOS E IA
    try:
        # 1. VERIFICAR LÍMITE DE TOKENS
        stats = db.query(AIUsageStats).filter(AIUsageStats.user_id == user.id).first()
        if not stats:
            stats = AIUsageStats(user_id=user.id)
            db.add(stats)
            db.commit()
            db.refresh(stats)

        if stats.daily_tokens_count >= stats.daily_limit:
            return {
                "text": "¡Hola! Soy Daiko. Has alcanzado tu límite de 50 consultas diarias. ¡Nos vemos mañana para seguir mejorando tus finanzas!",
                "type": "text"
            }

        # 2. OBTENER CONTEXTO REAL (Últimos 5 gastos del usuario)
        gastos = db.query(Transaction).filter(Transaction.user_id == user.id).limit(5).all()
        if gastos:
            resumen_gastos = "\n".join([f"- {g.description}: ${g.amount}" for g in gastos])
        else:
            resumen_gastos = "El usuario aún no tiene gastos registrados."

        # 3. LLAMADA A GEMINI
        prompt_final = f"{CONTEXTO_DAIKO}\n\nCONTEXTO GASTOS USUARIO:\n{resumen_gastos}\n\nPREGUNTA USUARIO: {pregunta}"
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )

        resultado = json.loads(response.text)

        # 4. ACTUALIZAR BASE DE DATOS
        nuevo_chat = AIChatHistory(
            user_id=user.id,
            user_message=pregunta,
            ai_response=resultado 
        )
        
        stats.daily_tokens_count += 1
        
        db.add(nuevo_chat)
        db.commit()

        return resultado 

    except Exception as e:
        db.rollback() 
        print(f"FALLO MASIVO EN MODO BYPASS: {str(e)}") 
        raise HTTPException(status_code=500, detail=f"El servidor explotó por: {str(e)}")


@router.get("/historial")
async def ver_historial(
    db: Session = Depends(get_db)
    # token: str = Depends(oauth2_scheme) <-- ELIMINADO PARA BYPASS
):
    print("--- INICIANDO HISTORIAL MODO BYPASS ---")
    try:
        # Forzamos el mismo usuario 39
        user = db.query(User).filter(User.id == 39).first()
        
        if not user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado para historial (ID 39)")
        
        chats = db.query(AIChatHistory).filter(
            AIChatHistory.user_id == user.id
        ).order_by(AIChatHistory.created_at.desc()).limit(10).all()
        
        return chats
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error consultando historial: {e}")
        raise HTTPException(status_code=500, detail="Error obteniendo el historial")
