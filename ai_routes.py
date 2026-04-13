import json
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import google.generativeai as genai
from dotenv import load_dotenv

# --- IMPORTACIONES PROPIAS ---
from database import get_db
from models import User, AIChatHistory, Transaction
from auth import verify_token 

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# Usamos flash para mayor velocidad
model = genai.GenerativeModel('gemini-2.5-flash') 

router = APIRouter(prefix="/ai", tags=["IA (Daiko)"])

CONTEXTO_DAIKO = """
ROLE: Eres DAIKO, experto financiero de la app Finara. Tu usuario es Kevin.
STRICT RULE: Responde directamente en español. 
NO te presentes, NO digas 'Hola', NO digas 'Muy bien Kevin'. 
Si el usuario pregunta algo personal, recuerda que eres su asistente en Finara.
ALWAYS output a valid JSON object with a "text" field.
"""

@router.get("/consultar")
async def consultar(
    pregunta: str, 
    db: Session = Depends(get_db), 
    token_data: dict = Depends(verify_token)
):
    # 1. IDENTIFICAR AL USUARIO
    user_email = token_data.get("sub")
    user = db.query(User).filter(User.email == user_email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # --- SECCIÓN COMENTADA PARA EVITAR ERRORES DE VALIDACIÓN (422) ---
    """
    # 2. OBTENER CONTEXTO DE GASTOS (Temporalmente deshabilitado)
    gastos = db.query(Transaction).filter(Transaction.user_id == user.id).order_by(Transaction.id.desc()).limit(10).all()
    resumen_gastos = "\n".join([f"- {g.description}: ${g.amount}" for g in gastos])

    # 3. OBTENER MEMORIA DEL CHAT (Temporalmente deshabilitado)
    historial_reciente = db.query(AIChatHistory).filter(
        AIChatHistory.user_id == user.id
    ).order_by(AIChatHistory.created_at.desc()).limit(3).all()
    historial_reciente.reverse()
    
    memoria_texto = ""
    for h in historial_reciente:
        respuesta_previa = h.ai_response["text"] if isinstance(h.ai_response, dict) else h.ai_response
        memoria_texto += f"Usuario: {h.user_message}\nDaiko: {respuesta_previa}\n"
    """
    # --- FIN DE SECCIÓN COMENTADA ---

    # 4. LLAMADA A GEMINI (Simplificada)
    try:
        # Prompt limpio para evitar errores de contexto
        prompt_final = f"""
        {CONTEXTO_DAIKO}
        
        PREGUNTA DEL USUARIO KEVIN:
        {pregunta}
        """
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        
        resultado = json.loads(response.text)

        # 5. GUARDAR EN LA BASE DE DATOS (Mantenemos el guardado para que luego puedas reactivar la memoria)
        try:
            nuevo_chat = AIChatHistory(
                user_id=user.id,
                user_message=pregunta,
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
        return {"text": "Lo siento Kevin, Daiko tiene un pequeño error de conexión. Intenta de nuevo.", "type": "error"}

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
