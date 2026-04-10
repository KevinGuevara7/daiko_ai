import json
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import google.generativeai as genai
from dotenv import load_dotenv

# --- IMPORTACIONES ---
from database import get_db
from models import User, AIChatHistory, Transaction
from auth import verify_token  # Importamos tu función de seguridad

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash') 

router = APIRouter(prefix="/ai", tags=["IA (Daiko)"])

CONTEXTO_DAIKO = """
ROLE: You are DAIKO, a financial expert for the Finara app.
STRICT RULE: Start your response IMMEDIATELY with the financial answer in Spanish. 
DO NOT introduce yourself or say 'Hola'. 
ALWAYS output a valid JSON object with a "text" field.
"""

@router.get("/consultar")
async def consultar(
    pregunta: str, 
    db: Session = Depends(get_db), 
    token_data: dict = Depends(verify_token) # Verifica el JWT
):
    # 1. IDENTIFICAR AL USUARIO DESDE EL TOKEN
    user_email = token_data.get("sub")
    user = db.query(User).filter(User.email == user_email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # 2. OBTENER CONTEXTO DE SUS GASTOS (Últimos 5)
    gastos = db.query(Transaction).filter(Transaction.user_id == user.id).limit(5).all()
    resumen_gastos = "\n".join([f"- {g.description}: ${g.amount}" for g in gastos])

    # 3. LLAMADA A GEMINI
    try:
        prompt_final = f"{CONTEXTO_DAIKO}\nCONTEXTO GASTOS:\n{resumen_gastos}\nPREGUNTA: {pregunta}"
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        resultado = json.loads(response.text)

        # 4. GUARDADO EN HISTORIAL (Vinculado al ID real)
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
            print(f"Error guardando en DB: {e_db}")

        return resultado

    except Exception as e:
        print(f"Error Gemini: {e}")
        return {"text": "Daiko está procesando datos financieros, reintenta en un momento.", "type": "text"}

@router.get("/historial")
async def ver_historial(
    db: Session = Depends(get_db), 
    token_data: dict = Depends(verify_token)
):
    # Extraemos el usuario del token para mostrar solo SU historial
    user_email = token_data.get("sub")
    user = db.query(User).filter(User.email == user_email).first()
    
    return db.query(AIChatHistory).filter(
        AIChatHistory.user_id == user.id
    ).order_by(AIChatHistory.created_at.desc()).limit(20).all()