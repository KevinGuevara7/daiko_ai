import json
import os
import re
import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, text
import google.generativeai as genai
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv

from database import get_db
from models import User, AIChatHistory

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def extraer_tickers_ia(pregunta: str) -> List[str]:
    modelo_extractor = genai.GenerativeModel(model_name="gemini-2.5-flash")
    prompt = f"Extrae los símbolos bursátiles (tickers de Yahoo Finance) de esta pregunta. Devuelve solo los símbolos separados por comas. Si no hay empresas, devuelve NINGUNO. Pregunta: '{pregunta}'"
    try:
        respuesta = modelo_extractor.generate_content(prompt)
        texto = respuesta.text.strip().upper()
        if "NINGUNO" in texto or not texto:
            return []
        return [t.strip() for t in texto.split(",") if t.strip()]
    except:
        return []

TICKER_FALLBACKS = {
    "GOOGL": "GOOG",
}

def obtener_analisis_bolsa(ticker: str) -> dict:
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
        except:
            continue

    if stock is None or hist is None or hist.empty:
        return {"error": f"No se encontraron datos para '{ticker}'."}

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
            "resumen_negocio": (full_info.get("longBusinessSummary", "")[:250] + "...")
        }
    except:
        return {"error": f"Error procesando datos de '{ticker}'."}

def analizar_gastos(contexto_gastos: List[dict]) -> str:
    if not contexto_gastos:
        return "No se proporcionaron gastos para analizar."
    total = sum(float(g.get("valor", 0)) for g in contexto_gastos)
    lineas = [f"  • {g.get('item', 'Sin nombre')}: ${float(g.get('valor', 0)):,.2f}" for g in contexto_gastos]
    return f"GASTOS REGISTRADOS:\n" + "\n".join(lineas) + f"\n  TOTAL: ${total:,.2f}"

model = genai.GenerativeModel(model_name="gemini-2.5-flash")
router = APIRouter(tags=["Finara AI"])

class ConsultaChat(BaseModel):
    pregunta: str
    session_id: str
    historial: List[dict] = []
    contexto_gastos: List[dict] = []
    user_name: Optional[str] = "Usuario"
    tool: Optional[str] = "rapido"

SYSTEM_PROMPT = """
Eres DAIKO, el motor de inteligencia financiera de Finara.
Tu propósito es ayudar a los usuarios a tomar decisiones financieras más inteligentes mediante análisis
precisos, datos reales y recomendaciones accionables.

PRINCIPIOS DE CONDUCTA:
- Responde SIEMPRE en español, con un tono profesional pero cercano.
- Fundamenta tus análisis en datos concretos. Evita suposiciones sin respaldo.
- Cuando dispongas de datos de mercado o gastos, úsalos como eje central de tu respuesta.
- Sé directo al identificar riesgos, oportunidades y patrones financieros relevantes.
- Nunca inventes cifras ni proyecciones si no tienes datos reales.

FORMATO DE RESPUESTA OBLIGATORIO:
Tu respuesta debe ser SIEMPRE un JSON válido con la siguiente estructura:
{
  "text": "<tu análisis completo aquí, puede incluir saltos de línea con \\n>"
}
No incluyas bloques de código, comillas adicionales ni texto fuera del JSON.
"""

INSTRUCCIONES_POR_MODO = {
    "bolsa": """
MODO: ANÁLISIS BURSÁTIL
Usa los datos de mercado provistos para entregar un análisis técnico completo que incluya:
1. Resumen del desempeño reciente (precio, rendimiento semanal, volumen).
2. Contexto del sector e industria.
3. Puntos fuertes y factores de riesgo identificables.
4. Una perspectiva objetiva sobre la situación actual del activo.
Si se proporcionan múltiples activos, realiza una comparativa entre ellos.
Evita dar recomendaciones de compra/venta directas; en su lugar, presenta escenarios.
""",
    "pensar": """
MODO: ANÁLISIS PROFUNDO
El usuario requiere un razonamiento financiero exhaustivo. Sigue este proceso:
1. Identifica el problema o pregunta central.
2. Desglosa los componentes relevantes (riesgo, liquidez, rentabilidad, contexto macroeconómico).
3. Evalúa alternativas con sus pros y contras.
4. Concluye con una síntesis objetiva y pasos sugeridos.
""",
    "gastos": """
MODO: AUDITORÍA DE GASTOS
Analiza los gastos del usuario con criterio financiero riguroso:
1. Identifica los rubros de mayor gasto y su proporción sobre el total.
2. Detecta posibles fugas de dinero o gastos redundantes.
3. Sugiere áreas de optimización con impacto estimado.
4. Propón una distribución más eficiente si aplica (ej. regla 50/30/20).
""",
    "rapido": """
MODO: CONSULTA RÁPIDA
Responde de forma concisa, clara y orientada a la acción.
Máximo 3-4 oraciones. Ve directo al punto sin perder precisión.
""",
}

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.name == data.user_name).first() or db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado en la base de datos.")

    instrucciones_modo = INSTRUCCIONES_POR_MODO.get(data.tool, INSTRUCCIONES_POR_MODO["rapido"])
    contexto_gastos = analizar_gastos(data.contexto_gastos)
    contexto_bolsa = ""

    if data.tool == "bolsa":
        tickers_detectados = extraer_tickers_ia(data.pregunta)
        if tickers_detectados:
            resultados_mercado = []
            errores = []
            for ticker in tickers_detectados:
                datos = obtener_analisis_bolsa(ticker)
                if "error" in datos:
                    errores.append(datos["error"])
                else:
                    resultados_mercado.append(datos)

            if resultados_mercado:
                contexto_bolsa = f"\nDATOS DE MERCADO EN TIEMPO REAL:\n{json.dumps(resultados_mercado, ensure_ascii=False, indent=2)}"
                if errores:
                    contexto_bolsa += f"\n\n[ADVERTENCIA PARCIAL: No se pudieron obtener datos para: {', '.join(errores)}]"
            else:
                contexto_bolsa = f"\n[ERROR: No fue posible obtener datos de mercado para los símbolos detectados: {', '.join(tickers_detectados)}. Informa al usuario e invítalo a verificar los símbolos o intentar más tarde.]"
        else:
            contexto_bolsa = "\n[INSTRUCCIÓN: El usuario no especificó una empresa. Pregúntale amablemente qué acción o sector desea analizar.]"

    historial_formateado = ""
    if data.historial:
        entradas = [f"{'Usuario' if msg.get('role') == 'user' else 'DAIKO'}: {msg.get('content', '')}" for msg in data.historial[-6:]]
        historial_formateado = "\nCONVERSACIÓN PREVIA:\n" + "\n".join(entradas)

    prompt_final = (
        f"{SYSTEM_PROMPT}\n"
        f"{instrucciones_modo}\n"
        f"{historial_formateado}\n"
        f"{contexto_gastos}\n"
        f"{contexto_bolsa}\n\n"
        f"Pregunta del usuario: {data.pregunta}"
    )

    try:
        response = model.generate_content(prompt_final)
        texto_raw = response.text.strip()
        texto_limpio = texto_raw.replace("`" * 3 + "json", "").replace("`" * 3, "").strip()

        try:
            resultado = json.loads(texto_limpio)
            if "text" not in resultado:
                resultado = {"text": texto_limpio}
        except:
            resultado = {"text": texto_limpio}

        es_primera_entrada = db.query(AIChatHistory).filter(AIChatHistory.session_id == data.session_id).count() == 0
        titulo_sesion = (data.pregunta[:40] + "...") if es_primera_entrada else None

        db.add(AIChatHistory(
            user_id=user.id,
            session_id=data.session_id,
            session_title=titulo_sesion,
            user_message=data.pregunta,
            ai_response=resultado
        ))
        db.commit()

        return resultado

    except Exception:
        return {"text": "Ocurrió un error al procesar tu consulta. Por favor, intenta nuevamente."}

@router.get("/sessions")
async def listar_sesiones(db: Session = Depends(get_db)):
    user = db.query(User).first()
    if not user:
        return []

    sesiones = (
        db.query(
            AIChatHistory.session_id,
            AIChatHistory.session_title,
            func.max(AIChatHistory.created_at).label("ultima_vez"),
        )
        .filter(AIChatHistory.user_id == user.id)
        .group_by(AIChatHistory.session_id, AIChatHistory.session_title)
        .order_by(text("ultima_vez DESC"))
        .all()
    )

    return [{"session_id": s.session_id, "title": s.session_title or "Conversación sin título", "ultima_vez": s.ultima_vez.isoformat()} for s in sesiones]

@router.get("/historial/{session_id}")
async def ver_historial_sesion(session_id: str, db: Session = Depends(get_db)):
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    registros = (
        db.query(AIChatHistory)
        .filter(AIChatHistory.user_id == user.id, AIChatHistory.session_id == session_id)
        .order_by(AIChatHistory.created_at.asc())
        .all()
    )

    return [{"user_message": r.user_message, "ai_response": r.ai_response.get("text", r.ai_response) if isinstance(r.ai_response, dict) else r.ai_response, "created_at": r.created_at.isoformat()} for r in registros]