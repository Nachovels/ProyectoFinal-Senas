from sqlalchemy import Column, Integer, SmallInteger, String, Text, Float, Enum, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base

class Rol(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), nullable=False)

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    rol_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    creado_en = Column(TIMESTAMP, server_default=func.now())

class Sesion(Base):
    __tablename__ = "sesiones"
    id = Column(Integer, primary_key=True, index=True)
    coordinador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    estudiante_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    codigo = Column(String(6), unique=True, nullable=True)
    iniciada_en = Column(TIMESTAMP, server_default=func.now())
    finalizada_en = Column(TIMESTAMP, nullable=True)
    
class Transcripcion(Base):
    __tablename__ = "transcripciones"
    id = Column(Integer, primary_key=True, index=True)
    sesion_id = Column(Integer, ForeignKey("sesiones.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tipo = Column(Enum("voz", "frase_rapida", "texto"), nullable=False)
    contenido = Column(Text, nullable=False)
    creado_en = Column(TIMESTAMP, server_default=func.now())

class FraseRapida(Base):
    __tablename__ = "frases_rapidas"
    id = Column(Integer, primary_key=True, index=True)
    contenido = Column(String(255), nullable=False)
    dirigida_a = Column(Enum("coordinador", "estudiante"), nullable=False)
    categoria = Column(String(50), default="General")
    activa = Column(Integer, default=1)

class Sena(Base):
    __tablename__ = "senas"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text)
    imagen_url = Column(String(255))
    video_url = Column(String(255))
    categoria = Column(Enum("abecedario", "contexto_estudiantil", "general"), nullable=False)

class RegistroIA(Base):
    __tablename__ = "registros_ia"
    id = Column(Integer, primary_key=True, index=True)
    sesion_id = Column(Integer, ForeignKey("sesiones.id"), nullable=False)
    sena_detectada = Column(String(100))
    confianza = Column(Float)
    creado_en = Column(TIMESTAMP, server_default=func.now())

class Auditoria(Base):
    __tablename__ = "auditoria"
    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    accion = Column(String(50), nullable=False)
    detalle = Column(Text, nullable=True)
    sesion_id = Column(Integer, ForeignKey("sesiones.id"), nullable=True)
    usuario_id = Column(Integer, nullable=True)
    creado_en = Column(TIMESTAMP, server_default=func.now())