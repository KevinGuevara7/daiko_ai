import yfinance as yf

class BolsaEngine:
    @staticmethod
    def obtener_analisis_completo(ticker_simbolo: str):
        try:
            ticker = yf.Ticker(ticker_simbolo)
            hist = ticker.history(period="5d")
            if hist.empty:
                return {"error": "Símbolo no encontrado"}

            info = ticker.info
            precio_actual = hist['Close'].iloc[-1]
            precio_inicial = hist['Close'].iloc[0]
            rendimiento = ((precio_actual - precio_inicial) / precio_inicial) * 100

            return {
                "nombre": info.get('longName', ticker),
                "precio": round(precio_actual, 2),
                "cambio_semanal": f"{round(rendimiento, 2)}%",
                "sector": info.get('sector', 'N/A'),
                "resumen": info.get('longBusinessSummary', '')[:150] + "..."
            }
        except Exception:
            return {"error": "Error al conectar con el mercado financiero."}

def obtener_analisis_bolsa(ticker: str):
    """
    Consulta información financiera en tiempo real de una empresa usando su símbolo (ticker).
    Ejemplos de ticker: 'AAPL' (Apple), 'NVDA' (NVIDIA), 'MSFT' (Microsoft).
    """
    engine = BolsaEngine()
    return engine.obtener_analisis_completo(ticker)