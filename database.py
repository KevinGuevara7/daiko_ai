import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# 1. Arreglamos el prefijo para SQLAlchemy
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 2. Forzamos el SSL directamente en la URL (Mejor práctica para Render externo)
if DATABASE_URL and "sslmode=require" not in DATABASE_URL:
    if "?" in DATABASE_URL:
        DATABASE_URL += "&sslmode=require"
    else:
        DATABASE_URL += "?sslmode=require"

# 3. Motor optimizado para conexiones EXTERNAS
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Verifica si la conexión externa sigue viva
    pool_recycle=300     # Recicla cada 5 minutos (evita el corte SSL de Render)
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
