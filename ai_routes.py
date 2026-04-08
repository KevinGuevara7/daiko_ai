@router.get("/consultar")
async def consultar(
    pregunta: str, 
    db: Session = Depends(get_db)
):
    print("--- RECONECTANDO DAIKO CON PROTECCIÓN ---")
    
    # 1. BUSCAR USUARIO (Si esto falla, el 404 te avisará)
    user = db.query(User).filter(User.id == 39).first()
    if not user:
        return {"text": "Error: Usuario 39 no encontrado en DB.", "type": "text"}

    # 2. INTENTAR LEER GASTOS (Si falla, Daiko sigue vivo)
    resumen_gastos = "No se pudo acceder a los gastos por error de conexión."
    try:
        gastos = db.query(Transaction).filter(Transaction.user_id == user.id).limit(5).all()
        if gastos:
            resumen_gastos = "\n".join([f"- {g.description}: ${g.amount}" for g in gastos])
        else:
            resumen_gastos = "El usuario no tiene gastos registrados."
    except Exception as e:
        print(f"Error leyendo gastos: {e}")

    # 3. LLAMADA A GEMINI
    try:
        prompt_final = f"{CONTEXTO_DAIKO}\n\nCONTEXTO GASTOS:\n{resumen_gastos}\n\nPREGUNTA: {pregunta}"
        response = model.generate_content(
            prompt_final,
            generation_config={"response_mime_type": "application/json"}
        )
        resultado = json.loads(response.text)
    except Exception as e:
        return {"text": f"Error en IA: {str(e)}", "type": "text"}

    # 4. INTENTAR GUARDAR (Si falla, igual te damos la respuesta)
    try:
        nuevo_chat = AIChatHistory(
            user_id=user.id,
            user_message=pregunta,
            ai_response=resultado
        )
        db.add(nuevo_chat)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"No se guardó el historial: {e}")

    return resultado
