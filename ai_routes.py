import json
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import google.generativeai as genai
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv

# --- IMPORTACIONES PROPIAS ---
from database import get_db
from models import User, AIChatHistory

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash') 

router = APIRouter(prefix="/ai", tags=["IA (Daiko)"])

class ConsultaChat(BaseModel):
    pregunta: str
    historial: List[dict]
    contexto_gastos: List[dict]
    user_name: Optional[str] = "Kevin"

CONTEXTO_DAIKO = """
ROLE: Eres DAIKO, el núcleo de inteligencia financiera de la app Finara. Tu usuario es Kevin.
STRICT RULE: Responde directamente en español. 
NO te presentes, NO digas 'Hola'. 
Usa los gastos adjuntos para dar consejos.
ALWAYS output a valid JSON object with a "text" field.
"""

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    # Buscamos a Kevin o al primer usuario para no fallar
    user = db.query(User).filter(User.name == "Kevin").first() or db.query(User).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="No hay usuarios")

    memoria_texto = ""
    for h in data.historial:
        role = "Usuario" if h["role"] == "user" else "Daiko"
        memoria_texto += f"{role}: {h['content']}\n"

    resumen_gastos = "\n".join([
        f"- {g.get('item', 'Gasto')}: ${g.get('valor', 0)}" for g in data.contexto_gastos
    ])

    try:
        prompt_final = f"{CONTEXTO_DAIKO}\nGastos:\n{resumen_gastos}\nMemoria:\n{memoria_texto}\nPregunta: {data.pregunta}"
        
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        
        resultado = json.loads(response.text)

        nuevo_chat = AIChatHistory(user_id=user.id, user_message=data.pregunta, ai_response=resultado)
        db.add(nuevo_chat)
        db.commit()

        return resultado

    except Exception as e:
        print(f"Error: {e}")
        return {"text": f"Error técnico: {str(e)}"}
