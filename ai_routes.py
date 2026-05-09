import json
import os
import yfinance as yf

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, text

import google.generativeai as genai

from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv

# --- IMPORTACIONES PROPIAS ---
from database import get_db
from models import User, AIChatHistory

# --- CONFIGURACIÓN ---
load_dotenv()

genai.configure(
    api_key=os.getenv("GEMINI_API_KEY")
)

# --- MOTOR DE ANÁLISIS DE BOLSA ---
def obtener_analisis_bolsa(ticker: str):
    try:
        stock = yf.Ticker(ticker)

        hist = stock.history(period="5d")

        if hist.empty:
            return {
                "error": f"No hay datos para {ticker}"
            }

        # Evitamos errores silenciosos de yfinance
        info = {}

        try:
            info = stock.info
        except Exception:
            info = {}

        actual = hist["Close"].iloc[-1]
        inicial = hist["Close"].iloc[0]

        rendimiento = ((actual - inicial) / inicial) * 100

        return {
            "nombre": info.get("longName", ticker),
            "precio": round(actual, 2),
            "cambio": f"{round(rendimiento, 2)}%",
            "sector": info.get("sector", "N/A")
        }

    except Exception as e:
        print(f"Error bolsa: {e}")

        return {
            "error": "Error de mercado"
        }

# --- CONTEXTO DEL MODELO ---
CONTEXTO = """
DAIKO: Inteligencia analítica de Finara.
Responde SIEMPRE en formato JSON válido.
Usa únicamente esta estructura:

{
  "text": "respuesta"
}
"""

# --- MODELO GEMINI ---
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    system_instruction=CONTEXTO
)

# --- ROUTER ---
router = APIRouter(tags=["Finara AI"])

# --- SCHEMA ---
class ConsultaChat(BaseModel):
    pregunta: str
    session_id: str
    historial: List[dict]
    contexto_gastos: List[dict]
    user_name: Optional[str] = "Kevin"

# --- ENDPOINT PRINCIPAL ---
@router.post("/consultar")
async def consultar(
    data: ConsultaChat,
    db: Session = Depends(get_db)
):
    # Buscar usuario
    user = db.query(User).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Usuario no encontrado"
        )

    try:
        # --- HISTORIAL PARA GEMINI ---
        h_gemini = []

        for m in data.historial:

            role = (
                "user"
                if m.get("role") == "user"
                else "model"
            )

            h_gemini.append({
                "role": role,
                "parts": [m.get("text", "")]
            })

        # --- CREAR CHAT ---
        chat = model.start_chat(
            history=h_gemini
        )

        # --- ENVIAR MENSAJE ---
        res = chat.send_message(
            data.pregunta
        )

        # --- RESPUESTA RAW ---
        t_raw = res.text

        # --- LIMPIEZA ---
        t_clean = t_raw.strip()

        # Eliminar markdown tipo ```json
        if t_clean.startswith("```"):
            t_clean = (
                t_clean
                .replace("```json", "")
                .replace("```", "")
                .strip()
            )

        # --- CONVERTIR A JSON ---
        try:
            resultado = json.loads(t_clean)

        except Exception:
            resultado = {
                "text": t_raw
            }

        # --- VALIDAR QUE EXISTA "text" ---
        if "text" not in resultado:
            resultado = {
                "text": str(resultado)
            }

        # --- VERIFICAR SI ES NUEVA SESIÓN ---
        es_nuevo = (
            db.query(AIChatHistory)
            .filter(
                AIChatHistory.session_id == data.session_id
            )
            .count()
            == 0
        )

        # --- GUARDAR EN BD ---
        nuevo = AIChatHistory(
            user_id=user.id,
            session_id=data.session_id,
            session_title=(
                data.pregunta[:30]
                if es_nuevo
                else None
            ),
            user_message=data.pregunta,
            ai_response=resultado
        )

        db.add(nuevo)
        db.commit()

        return resultado

    except Exception as e:

        print(f"Error general: {e}")

        return {
            "text": "Error en el servidor"
        }

# --- LISTAR SESIONES ---
@router.get("/sessions")
async def listar_sesiones(
    db: Session = Depends(get_db)
):
    sesiones = (
        db.query(
            AIChatHistory.session_id,
            AIChatHistory.session_title
        )
        .distinct()
        .all()
    )

    return [
        {
            "session_id": s.session_id,
            "title": s.session_title or "Chat"
        }
        for s in sesiones
    ]

# --- VER HISTORIAL ---
@router.get("/historial/{session_id}")
async def ver_historial(
    session_id: str,
    db: Session = Depends(get_db)
):
    registros = (
        db.query(AIChatHistory)
        .filter(
            AIChatHistory.session_id == session_id
        )
        .all()
    )

    return [
        {
            "user": r.user_message,
            "ai": r.ai_response
        }
        for r in registros
    ]