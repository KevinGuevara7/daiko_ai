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
