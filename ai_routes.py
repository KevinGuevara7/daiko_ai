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

# FIX 1: Extraer MÚLTIPLES tickers usando Gemini (Inteligencia Artificial)
def extraer_tickers_ia(pregunta: str) -> List[str]:
    """
    Extrae todos los símbolos bursátiles de la pregunta del usuario usando IA.
    Reemplaza la necesidad de diccionarios manuales y detecta nombres naturales.
    """
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

# FIX 2: Fallback GOOGL → GOOG cuando Yahoo Finance no devuelve datos
TICKER_FALLBACKS = {
    "GOOGL": "GOOG",
}

def obtener_analisis_bolsa(ticker: str) -> dict:
    """
    Consulta información financiera en tiempo real usando Yahoo Finance.
    Retorna precio, rendimiento semanal, sector, volumen y resumen del negocio.
    Incluye fallback para tickers con símbolos alternativos (ej. GOOGL → GOOG).
    """
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
                ticker = intento  # usar el símbolo que funcionó
                break
        except Exception as e:
            print(f"[DAIKO] Intento fallido para '{intento}': {e}")
            continue

    if stock is None or hist is None or hist.empty:
        return {
            "error": f"No se encontraron datos para '{ticker}'. "
            f"Verifica que el símbolo sea correcto o intenta más tarde."
        }

    try:
        full_info = stock.info
        precio_actual = round(float(hist["Close"].iloc[-1]), 2)
        precio_inicial = round(float(hist["Close"].iloc[0]), 2)
        rendimiento_semanal = round(
            ((precio_actual - precio_inicial) / precio_inicial) * 100, 2
        )
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
    """
    Genera un resumen estructurado de los gastos para incluir en el prompt.
    """
    if not contexto_gastos:
        return "No se proporcionaron gastos para analizar."

    total = sum(float(g.get("valor", 0)) for g in contexto_gastos)
    lineas = [
        f"  • {g.get('item', 'Sin nombre')}: ${float(g.get('valor', 0)):,.2f}"
        for g in contexto_gastos
    ]
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

FORMATO DE RESPUESTA:
Responde directamente en texto claro, estructurado o usando Markdown (negritas, listas). NO uses formato JSON ni envuelvas tu respuesta en llaves {}.
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


# ---------------------------------------------------------------------------
# ENDPOINT PRINCIPAL
# ---------------------------------------------------------------------------

@router.post("/consultar")
async def consultar(data: ConsultaChat, db: Session = Depends(get_db)):
    # Búsqueda estricta por usuario (Evita límites/historiales globales)
    user = db.query(User).filter(User.name == data.user_name).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado en la base de datos.")

    # --- VALIDACIÓN DE LÍMITES DIARIOS (UTC) ---
    hoy_utc = datetime.now(timezone.utc).date()
    consultas_hoy = (
        db.query(AIChatHistory)
        .filter(
            AIChatHistory.user_id == user.id,
            func.date(AIChatHistory.created_at) == hoy_utc,
            AIChatHistory.tool == data.tool
        )
        .count()
    )

    limite_permitido = LIMITES_DIARIOS.get(data.tool, 5)
    if consultas_hoy >= limite_permitido:
        return {
            "text": f"Has alcanzado el límite diario de {limite_permitido} consultas para el apartado de {data.tool}. Por favor, vuelve a intentarlo mañana."
        }
    # -------------------------------------------

    # Seleccionar instrucciones del modo
    instrucciones_modo = INSTRUCCIONES_POR_MODO.get(data.tool, INSTRUCCIONES_POR_MODO["rapido"])

    # Contexto de gastos
    contexto_gastos = analizar_gastos(data.contexto_gastos)

    # Contexto de bolsa con soporte multi-ticker (Ahora con IA)
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
                contexto_bolsa = (
                    f"\nDATOS DE MERCADO EN TIEMPO REAL:\n"
                    f"{json.dumps(resultados_mercado, ensure_ascii=False, indent=2)}"
                )
                # Adjuntar errores parciales si algún ticker falló
                if errores:
                    contexto_bolsa += (
                        f"\n\n[ADVERTENCIA PARCIAL: No se pudieron obtener datos para: "
                        f"{', '.join(errores)}]"
                    )
            else:
                # Todos los tickers fallaron
                contexto_bolsa = (
                    f"\n[ERROR: No fue posible obtener datos de mercado para los símbolos "
                    f"detectados: {', '.join(tickers_detectados)}. "
                    f"Informa al usuario e invítalo a verificar los símbolos o intentar más tarde.]"
                )
        else:
            contexto_bolsa = (
                "\n[INSTRUCCIÓN: El usuario no especificó una empresa. Pregúntale amablemente qué acción o sector desea analizar.]"
            )

    # Construir historial de conversación para el modelo
    historial_formateado = ""
    if data.historial:
        entradas = []
        for msg in data.historial[-6:]:
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

        # Limpiar posibles bloques de código markdown de manera segura
        texto_limpio = texto_raw.replace("`" * 3 + "json", "").replace("`" * 3, "").strip()

        # Envolvemos la respuesta directamente (Sin intentar leer JSON)
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
            tool=data.tool 
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
async def listar_sesiones(user_name: str, db: Session = Depends(get_db)):
    # Búsqueda estricta por usuario
    user = db.query(User).filter(User.name == user_name).first()
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
async def ver_historial_sesion(session_id: str, user_name: str, db: Session = Depends(get_db)):
    # Búsqueda estricta por usuario
    user = db.query(User).filter(User.name == user_name).first()
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


# ---------------------------------------------------------------------------
# ELIMINAR UNA SESIÓN (NUEVO ENDPOINT)
# ---------------------------------------------------------------------------

@router.delete("/sessions/{session_id}")
async def eliminar_sesion(session_id: str, user_name: str, db: Session = Depends(get_db)):
    # Búsqueda estricta por usuario
    user = db.query(User).filter(User.name == user_name).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    # Buscar todos los mensajes de esa sesión que pertenezcan al usuario
    registros = (
        db.query(AIChatHistory)
        .filter(
            AIChatHistory.user_id == user.id,
            AIChatHistory.session_id == session_id
        )
        .all()
    )

    if not registros:
        raise HTTPException(status_code=404, detail="Sesión no encontrada.")

    # Eliminar los registros
    for r in registros:
        db.delete(r)
        
    db.commit()

    return {"message": "Sesión eliminada correctamente"}


# ---------------------------------------------------------------------------
# OBTENER CRÉDITOS IA (CORREGIDO PARA FLUTTER)
# ---------------------------------------------------------------------------

@router.get("/creditos")
async def obtener_creditos(user_name: str, db: Session = Depends(get_db)):
    try:
        # Búsqueda estricta por usuario (usando el user_name que envía Flutter)
        user = db.query(User).filter(User.name == user_name).first()
        
        # Si el usuario es nuevo, le mandamos los límites máximos por defecto
        if not user:
            return LIMITES_DIARIOS

        hoy_utc = datetime.now(timezone.utc).date()
        
        # Contamos cuántas consultas ha hecho hoy, agrupadas por herramienta
        consultas = (
            db.query(AIChatHistory.tool, func.count(AIChatHistory.id))
            .filter(
                AIChatHistory.user_id == user.id,
                func.date(AIChatHistory.created_at) == hoy_utc,
                AIChatHistory.tool.isnot(None)
            )
            .group_by(AIChatHistory.tool)
            .all()
        )

        # Convertimos el resultado a un diccionario: ej. {"rapido": 2, "bolsa": 1}
        usos_hoy = {tool: count for tool, count in consultas}

        # Calculamos los restantes restando el límite diario menos los usos de hoy
        creditos_restantes = {}
        for tool, limite in LIMITES_DIARIOS.items():
            usados = usos_hoy.get(tool, 0)
            creditos_restantes[tool] = max(0, limite - usados)

        # Devolverá exactamente lo que Flutter busca: {"bolsa": 2, "gastos": 1, "rapido": 3, "pensar": 3}
        return creditos_restantes

    except Exception as e:
        print(f"[DAIKO] Error consultando créditos: {e}")
        # Valor de contingencia si falla la base de datos (todo en 0)
        return {tool: 0 for tool in LIMITES_DIARIOS.keys()}
