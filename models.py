from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, Float, Text, Boolean, func
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from database import Base

# Tabla of Roles
class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)

    users = relationship("User", back_populates="role")

# Table users
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    password = Column(String)

    role_id = Column(Integer, ForeignKey("roles.id"))
    role = relationship("Role", back_populates="users")

    # Relaciones con cascada (Si borras al usuario, se limpia todo lo demás)
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    reset_tokens = relationship("PasswordResetToken", backref="user", cascade="all, delete-orphan")
    ai_stats = relationship("AIUsageStats", back_populates="user", uselist=False, cascade="all, delete-orphan")
    ai_history = relationship("AIChatHistory", back_populates="user", cascade="all, delete-orphan")

#Table transaction
class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Float)
    type = Column(String)
    description = Column(String)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    user = relationship("User", back_populates="transactions")

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    token = Column(String, unique=True, index=True)
    expires_at = Column(DateTime)
#Table videos
class VideoCategory(Base):
    __tablename__ = "video_categories"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    description = Column(String)

    videos = relationship("Video", back_populates="category", cascade="all, delete-orphan")

class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    url = Column(String)

    category_id = Column(Integer, ForeignKey("video_categories.id", ondelete="CASCADE"))
    category = relationship("VideoCategory", back_populates="videos")

# --- TABLAS DE IA ---

class AIUsageStats(Base):
    __tablename__ = "ai_usage_stats"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    daily_tokens_count = Column(Integer, default=0)
    daily_limit = Column(Integer, default=50)

    # Cambiamos a server_default para que la DB maneje la hora
    last_query_timestamp = Column(DateTime, server_default=func.now(), onupdate=func.now())
    is_premium = Column(Boolean, default=False)

    user = relationship("User", back_populates="ai_stats")

class AIChatHistory(Base):
    __tablename__ = "ai_chat_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    user_message = Column(Text)
    ai_response = Column(JSONB) 
    
    # IMPORTANTE: server_default evita errores de "can't adapt type"
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="ai_history")