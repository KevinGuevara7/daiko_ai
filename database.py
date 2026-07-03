import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# 1. Arreglamos el prefijo para SQLAlchemy moderno
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 2. Configuración dinámica de SSL
# Solo exigimos SSL si detectamos que es una URL externa de Render
argumentos_conexion = {}
if DATABASE_URL and "render.com" in DATABASE_URL:
    argumentos_conexion["sslmode"] = "require"

# 3. Motor optimizado
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  
    pool_recycle=300,    
    connect_args=argumentos_conexion
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
