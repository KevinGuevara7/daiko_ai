import json
import os
import re
from datetime import datetime, timezone
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

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

model = genai.GenerativeModel(model_name="gemini-2.5-flash")
router = APIRouter(tags=["Finara AI"])

# ---------------------------------------------------------------------------
# LIMITES DIARIOS POR HERRAMIENTA
# ---------------------------------------------------------------------------
LIMITES_DIARIOS = {
    "bolsa": 2,
    "gastos": 1,
    "rapido": 3,
    "pensar": 3
}

# ---------------------------------------------------------------------------
# HERRAMIENTA: ANÁLISIS DE BOLSA
# ---------------------------------------------------------------------------

def extraer_tickers_ia(pregunta: str) -> List[str]:
    """Extrae símbolos bursátiles usando IA."""
    modelo_extractor = genai.GenerativeModel(model_name="gemini-2.5-flash")
    prompt = f"Extrae los símbolos bursátiles (tickers de Yahoo Finance) de esta pregunta. Devuelve solo los símbolos separados por comas. Si no hay empresas, devuelve NINGUNO. Pregunta: '{pregunta}'"
    try:
        respuesta = modelo_extractor.generate_content(prompt)
        texto = respuesta.text.strip().upper()
        if "NINGUNO" in texto or not texto:
            return []
        return [t.strip() for t in texto.split(",") if t.strip()]
    except Exception as e:
        print(f"[DAIKO] Error en extracción IA: {e}")
        return []

TICKER_FALLBACKS = {
    "GOOGL": "GOOG",
}

def obtener_analisis_bolsa(ticker: str) -> dict:
    """Consulta información financiera en Yahoo Finance."""
    intentos = [ticker]
    if ticker in TICKER_FALLBACKS:
        intentos.append(TICKER_FALLBACKS[ticker])

    stock = None
    hist = None

    for intento in intentos:
        try:
            s = yf.Ticker(intento)
            h = s.history(period="5d")
            if not h.empty:
                stock = s
                hist = h
                ticker = intento 
                break
        except Exception as e:
            print(f"[DAIKO] Intento fallido para '{intento}': {e}")
            continue

    if stock is None or hist is None or hist.empty:
        return {"error": f"No se encontraron datos para '{ticker}'. Verifica el símbolo."}

    try:
        full_info = stock.info
        precio_actual = round(float(hist["Close"].iloc[-1]), 2)
        precio_inicial = round(float(hist["Close"].iloc[0]), 2)
        rendimiento_semanal = round(((precio_actual - precio_inicial) / precio_inicial) * 100, 2)
        volumen_promedio = int(hist["Volume"].mean())

        return {
            "ticker": ticker,
            "nombre": full_info.get("longName", ticker),
            "precio_actual_usd": precio_actual,
            "precio_hace_5d_usd": precio_inicial,
            "rendimiento_semanal": f"{rendimiento_semanal:+.2f}%",
            "volumen_promedio_5d": f"{volumen_promedio:,}",
            "sector": full_info.get("sector", "No disponible"),
            "industria": full_info.get("industry", "No disponible"),
            "pais": full_info.get("country", "No disponible"),
            "resumen_negocio": (full_info.get("longBusinessSummary", "")[:250] + "..."),
        }
    except Exception as e:
        print(f"[DAIKO] Error procesando datos de '{ticker}': {e}")
        return {"error": f"No fue posible procesar los datos de '{ticker}'. Intenta más tarde."}

# ---------------------------------------------------------------------------
# HERRAMIENTA: ANÁLISIS DE GASTOS
# ---------------------------------------------------------------------------

def analizar_gastos(contexto_gastos: List[dict]) -> str:
    if not contexto_gastos:
        return "No se proporcionaron gastos para analizar."
    total = sum(float(g.get("valor", 0)) for g in contexto_gastos)
    lineas = [f"  • {g.get('item', 'Sin nombre')}: ${float(g.get('valor', 0)):,.2f}" for g in contexto_gastos]
    resumen = "\n".join(lineas)
    return f"GASTOS REGISTRADOS:\n{resumen}\n  TOTAL: ${total:,.2f}"


# ---------------------------------------------------------------------------
# ESQUEMA DE DATOS Y PROMPTS
# ---------------------------------------------------------------------------

class ConsultaChat(BaseModel):
    pregunta: str
    session_id: str
    historial: List[dict] = []
    contexto_gastos: List[dict] = []
    user_name: Optional[str] = "Usuario"
    tool: Optional[str] = "rapido"

SYSTEM_PROMPT = """
Eres DAIKO, el motor de inteligencia financiera de Finara.
Responde SIEMPRE en español, fundamentado en datos. NO uses JSON en la respuesta.
"""

INSTRUCCIONES_POR_MODO = {
    "bolsa": "MODO BURSÁTIL: Usa los datos de mercado para un análisis técnico. No des recomendaciones de compra directas.",
    "pensar": "MODO PROFUNDO: Razonamiento financiero exhaustivo con pros, contras y pasos sugeridos.",
    "gastos": "MODO AUDITORÍA: Analiza gastos, detecta fugas y sugiere optimizaciones.",
    "rapido": "MODO RÁPIDO: Sé muy conciso (máx 3-4 oraciones).",
}

# ---------------------------------------------------------------------------
# ENDPOINTS
# ---------------------------------------------------------------------------

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == data.user_name).first()
    if not user: raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    hoy_utc = datetime.now(timezone.utc).date()
    consultas_hoy = db.query(AIChatHistory).filter(
        AIChatHistory.user_id == user.id,
        func.date(AIChatHistory.created_at) == hoy_utc,
        AIChatHistory.tool == data.tool
    ).count()

    limite_permitido = LIMITES_DIARIOS.get(data.tool, 5)
    if consultas_hoy >= limite_permitido:
        return {"text": f"Has alcanzado el límite diario de {limite_permitido} para {data.tool}. Intenta mañana."}

    instrucciones_modo = INSTRUCCIONES_POR_MODO.get(data.tool, INSTRUCCIONES_POR_MODO["rapido"])
    contexto_gastos = analizar_gastos(data.contexto_gastos)
    contexto_bolsa = ""

    if data.tool == "bolsa":
        tickers = extraer_tickers_ia(data.pregunta)
        if tickers:
            resultados = [obtener_analisis_bolsa(t) for t in tickers]
            exitosos = [r for r in resultados if "error" not in r]
            errores = [r["error"] for r in resultados if "error" in r]
            
            if exitosos: contexto_bolsa += f"\nDATOS MERCADO:\n{json.dumps(exitosos, ensure_ascii=False, indent=2)}"
            if errores: contexto_bolsa += f"\n[ERRORES: {', '.join(errores)}]"
            if not exitosos: contexto_bolsa = "\n[ERROR: No se obtuvieron datos. Informa al usuario.]"
        else:
            contexto_bolsa = "\n[INSTRUCCIÓN: Pregunta qué empresa analizar.]"

    historial_formateado = ""
    if data.historial:
        entradas = [f"{'Usuario' if m.get('role') == 'user' else 'DAIKO'}: {m.get('content', '')}" for m in data.historial[-6:]]
        historial_formateado = "\nCONVERSACIÓN PREVIA:\n" + "\n".join(entradas)

    prompt_final = f"{SYSTEM_PROMPT}\n{instrucciones_modo}\n{historial_formateado}\n{contexto_gastos}\n{contexto_bolsa}\n\nPregunta: {data.pregunta}"

    try:
        response = model.generate_content(prompt_final)
        texto_limpio = response.text.strip().replace("```json", "").replace("```", "").strip()
        resultado = {"text": texto_limpio}

        es_primera = db.query(AIChatHistory).filter(AIChatHistory.session_id == data.session_id).count() == 0
        titulo = (data.pregunta[:40] + "...") if es_primera else None

        db.add(AIChatHistory(
            user_id=user.id, session_id=data.session_id, session_title=titulo,
            user_message=data.pregunta, ai_response=resultado, tool=data.tool
