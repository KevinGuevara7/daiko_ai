import yfinance as yf

class BolsaEngine:
    """
    Motor de análisis de bolsa independiente para la IA.
    No requiere API Keys y es gratuito.
    """

    @staticmethod
    def obtener_precio_actual(ticker_simbolo):
        """Devuelve el precio de cierre más reciente."""
        ticker = yf.Ticker(ticker_simbolo)
        # Traemos solo el último día para velocidad
        data = ticker.history(period="1d")
        if data.empty:
            return None
        return round(data['Close'].iloc[-1], 2)

    @staticmethod
    def obtener_analisis_completo(ticker_simbolo):
        """
        Extrae datos profundos para que la IA tome decisiones.
        Incluye precio, tendencia de 5 días y sector.
        """
        ticker = yf.Ticker(ticker_simbolo)
        hist = ticker.history(period="5d")
        
        if hist.empty:
            return {"error": "Símbolo no encontrado"}

        precio_actual = hist['Close'].iloc[-1]
        precio_inicial = hist['Close'].iloc[0]
        rendimiento_semanal = ((precio_actual - precio_inicial) / precio_inicial) * 100

        return {
            "simbolo": ticker_simbolo,
            "nombre": ticker.info.get('longName', 'N/A'),
            "precio_actual": round(precio_actual, 2),
            "tendencia_semanal_pct": round(rendimiento_semanal, 2),
            "sector": ticker.info.get('sector', 'Desconocido'),
            "resumen": ticker.info.get('longBusinessSummary', 'Sin descripción')[:200] + "..."
        }

# --- PRUEBA RÁPIDA ---
# motor = BolsaEngine()
# print(motor.obtener_analisis_completo("NVDA"))