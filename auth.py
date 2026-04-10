import os
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "tu_clave_secreta_aqui")
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

def verify_token(token: str = Depends(oauth2_scheme)):
    print(f"--- DEBUG AUTH START ---")
    print(f"TOKEN RECIBIDO: {token[:10]}...") # Solo los primeros 10 caracteres por seguridad
    try:
        # Intentamos decodificar
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        print(f"DEBUG AUTH: Decodificación exitosa para: {payload.get('sub')}")
        return payload
    except JWTError as e:
        print(f"DEBUG AUTH ERROR: {str(e)}")
        # Aquí sabremos si es 'Signature verification failed' (Clave secreta mal)
        # o 'Signature has expired' (Tiempo agotado)
        raise HTTPException(
            status_code=401, 
            detail=f"Error de Autenticación: {str(e)}"
        )