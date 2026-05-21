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

# --- IMPORTACIONES PROPIAS ---
from database import get_db
from models import User, AIChatHistory

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ---------------------------------------------------------------------------
# HERRAMIENTA: ANÁLISIS DE BOLSA
# ---------------------------------------------------------------------------

TICKER_ALIASES = {
    "APPLE": "AAPL", "GOOGLE": "GOOGL", "ALPHABET": "GOOGL",
    "AMAZON": "AMZN", "MICROSOFT": "MSFT", "TESLA": "TSLA",
    "META": "META", "NVIDIA": "NVDA", "NETFLIX": "NFLX",
}

def extraer_ticker(pregunta: str) -> Optional[str]:
    """
    Extrae el símbolo bursátil de la pregunta del usuario.
    Prioriza tickers explícitos en mayúsculas (ej. AAPL, TSLA) o nombres comunes conocidos.
    """
    palabras = pregunta.upper().split()

    # 1. Buscar alias conocidos
    for palabra in palabras:
        limpia = re.sub(r"[^A-Z]", "", palabra)
        if limpia in TICKER_ALIASES:
            return TICKER_ALIASES[limpia]

    # 2. Buscar ticker explícito: entre 1 y 5 letras mayúsculas puras
    for palabra in palabras:
        if re.fullmatch(r"[A-Z]{1,5}", palabra):
            return palabra

    return None


def obtener_analisis_bolsa(ticker: str) -> dict:
    """
    Consulta información financiera en tiempo real usando Yahoo Finance.
    Retorna precio, rendimiento semanal, sector, volumen y resumen del negocio.
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")

        if hist.empty:
            return {"error": f"No se encontraron datos para el ticker '{ticker}'. Verifica que el símbolo sea correcto."}

        info = stock.fast_info
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
        print(f"[DAIKO] Error Yahoo Finance para '{ticker}': {e}")
        return {"error": f"No fue posible obtener datos de mercado para '{ticker}'. Intenta más tarde."}


# ---------------------------------------------------------------------------
# HERRAMIENTA: ANÁLISIS DE GASTOS
# ---------------------------------------------------------------------------

def analizar_gastos(contexto_gastos: List[dict]) -> str:
    """
    Genera un resumen estructurado de los gastos para incluir en el prompt.
    """
    if not contexto_gastos:
        return "No se proporcionaron gastos para analizar."

    total = sum(float(g.get("valor", 0)) for g in contexto_gastos)
    lineas = [f"  • {g.get('item', 'Sin nombre')}: ${float(g.get('valor', 0)):,.2f}" for g in contexto_gastos]
    resumen = "\n".join(lineas)
    return f"GASTOS REGISTRADOS:\n{resumen}\n  TOTAL: ${total:,.2f}"


# ---------------------------------------------------------------------------
# CONFIGURACIÓN DEL MODELO
# ---------------------------------------------------------------------------

model = genai.GenerativeModel(model_name="gemini-2.5-flash")
router = APIRouter(tags=["Finara AI"])


# ---------------------------------------------------------------------------
# ESQUEMA DE DATOS
# ---------------------------------------------------------------------------

class ConsultaChat(BaseModel):
    pregunta: str
    session_id: str
    historial: List[dict] = []
    contexto_gastos: List[dict] = []
    user_name: Optional[str] = "Usuario"
    tool: Optional[str] = "rapido"


# ---------------------------------------------------------------------------
# SYSTEM PROMPT PROFESIONAL
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ENDPOINT PRINCIPAL
# ---------------------------------------------------------------------------

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    # Obtener usuario
    user = (
        db.query(User).filter(User.name == data.user_name).first()
        or db.query(User).first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado en la base de datos.")

    # Seleccionar instrucciones del modo
    instrucciones_modo = INSTRUCCIONES_POR_MODO.get(data.tool, INSTRUCCIONES_POR_MODO["rapido"])

    # Contexto de gastos
    contexto_gastos = analizar_gastos(data.contexto_gastos)

    # Contexto de bolsa (solo en modo bolsa)
    contexto_bolsa = ""
    ticker_detectado = None
    if data.tool == "bolsa":
        ticker_detectado = extraer_ticker(data.pregunta)
        if ticker_detectado:
            datos_mercado = obtener_analisis_bolsa(ticker_detectado)
            contexto_bolsa = f"\nDATOS DE MERCADO EN TIEMPO REAL:\n{json.dumps(datos_mercado, ensure_ascii=False, indent=2)}"
        else:
            contexto_bolsa = "\n[ADVERTENCIA: No se detectó un ticker válido en la pregunta. Solicita al usuario que especifique el símbolo, ej: AAPL, TSLA, AMZN.]"

    # Construir historial de conversación para el modelo
    historial_formateado = ""
    if data.historial:
        entradas = []
        for msg in data.historial[-6:]:  # últimos 6 turnos para no exceder contexto
            rol = "Usuario" if msg.get("role") == "user" else "DAIKO"
            entradas.append(f"{rol}: {msg.get('content', '')}")
        historial_formateado = "\nCONVERSACIÓN PREVIA:\n" + "\n".join(entradas)

    # Ensamblar prompt final
    prompt_final = (
        f"{SYSTEM_PROMPT}\n"
        f"{instrucciones_modo}\n"
        f"{historial_formateado}\n"
        f"{contexto_gastos}\n"
        f"{contexto_bolsa}\n\n"
        f"Pregunta del usuario: {data.pregunta}"
    )

    # Llamada al modelo
    try:
        response = model.generate_content(prompt_final)
        texto_raw = response.text.strip()

        # Limpiar posibles bloques de código markdown
        texto_limpio = re.sub(r"^```(?:json)?\s*", "", texto_raw)
        texto_limpio = re.sub(r"\s*```$", "", texto_limpio).strip()

        try:
            resultado = json.loads(texto_limpio)
            if "text" not in resultado:
                resultado = {"text": texto_limpio}
        except json.JSONDecodeError:
            resultado = {"text": texto_limpio}

        # Guardar en base de datos
        es_primera_entrada = (
            db.query(AIChatHistory)
            .filter(AIChatHistory.session_id == data.session_id)
            .count() == 0
        )
        titulo_sesion = (data.pregunta[:40] + "...") if es_primera_entrada else None

        db.add(AIChatHistory(
            user_id=user.id,
            session_id=data.session_id,
            session_title=titulo_sesion,
            user_message=data.pregunta,
            ai_response=resultado,
        ))
        db.commit()

        return resultado

    except Exception as e:
        print(f"[DAIKO] Error al generar respuesta: {e}")
        return {"text": "Ocurrió un error al procesar tu consulta. Por favor, intenta nuevamente."}


# ---------------------------------------------------------------------------
# SESIONES
# ---------------------------------------------------------------------------

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

    return [
        {
            "session_id": s.session_id,
            "title": s.session_title or "Conversación sin título",
            "ultima_vez": s.ultima_vez.isoformat(),
        }
        for s in sesiones
    ]


# ---------------------------------------------------------------------------
# HISTORIAL DE SESIÓN
# ---------------------------------------------------------------------------

@router.get("/historial/{session_id}")
async def ver_historial_sesion(session_id: str, db: Session = Depends(get_db)):
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    registros = (
        db.query(AIChatHistory)
        .filter(
            AIChatHistory.user_id == user.id,
            AIChatHistory.session_id == session_id,
        )
        .order_by(AIChatHistory.created_at.asc())
        .all()
    )

    return [
        {
            "user_message": r.user_message,
            "ai_response": (
                r.ai_response.get("text", r.ai_response)
                if isinstance(r.ai_response, dict)
                else r.ai_response
            ),
            "created_at": r.created_at.isoformat(),
        }
        for r in registros
    ]