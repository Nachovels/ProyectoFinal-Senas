from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.core.database import engine, Base, SessionLocal
from app.models import models
from datetime import datetime
import json

Base.metadata.create_all(bind=engine)

app = FastAPI(title="SpeakingHands")

# ── Conexiones activas ─────────────────────────────────────────
class SalaManager:
    def __init__(self):
        self.coordinador: WebSocket = None
        self.estudiantes: list[WebSocket] = []
        self.sesion_id: int = None

    def iniciar_sesion(self, db: Session):
        coord = db.query(models.Usuario).filter_by(rol_id=2).first()
        if not coord:
            coord = models.Usuario(
                nombre="Coordinador Demo",
                email="coordinador@demo.cl",
                password="demo",
                rol_id=2
            )
            db.add(coord)
            db.commit()
            db.refresh(coord)

        sesion = models.Sesion(coordinador_id=coord.id)
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
        self.sesion_id = sesion.id
        return sesion.id

    def cerrar_sesion(self, db: Session):
        if self.sesion_id:
            sesion = db.query(models.Sesion).filter_by(id=self.sesion_id).first()
            if sesion:
                sesion.finalizada_en = datetime.now()
                db.commit()
        self.sesion_id = None

    def guardar_transcripcion(self, db: Session, contenido: str, tipo: str, usuario_id: int = 1):
        if not self.sesion_id:
            return
        t = models.Transcripcion(
            sesion_id=self.sesion_id,
            usuario_id=usuario_id,
            tipo=tipo,
            contenido=contenido
        )
        db.add(t)
        db.commit()

sala = SalaManager()

# ── Rutas HTML ─────────────────────────────────────────────────
@app.get("/")
async def index():
    with open("../frontend/templates/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/estudiante")
async def estudiante():
    with open("../frontend/templates/estudiante.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# ── API: Historial ─────────────────────────────────────────────
@app.get("/api/historial")
async def get_historial():
    db: Session = SessionLocal()
    try:
        sesiones = db.query(models.Sesion).order_by(models.Sesion.iniciada_en.desc()).limit(20).all()
        resultado = []
        for s in sesiones:
            transcripciones = (
                db.query(models.Transcripcion)
                .filter_by(sesion_id=s.id)
                .order_by(models.Transcripcion.creado_en)
                .all()
            )
            resultado.append({
                "id": s.id,
                "iniciada_en": s.iniciada_en.strftime("%d/%m/%Y %H:%M") if s.iniciada_en else "",
                "finalizada_en": s.finalizada_en.strftime("%H:%M") if s.finalizada_en else "En curso",
                "mensajes": [
                    {
                        "tipo": t.tipo,
                        "contenido": t.contenido,
                        "hora": t.creado_en.strftime("%H:%M") if t.creado_en else ""
                    } for t in transcripciones
                ]
            })
        return resultado
    finally:
        db.close()

# ── WebSocket Coordinador ──────────────────────────────────────
@app.websocket("/ws/coordinador")
async def ws_coordinador(websocket: WebSocket):
    await websocket.accept()
    sala.coordinador = websocket
    db: Session = SessionLocal()
    sala.iniciar_sesion(db)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            sala.guardar_transcripcion(db, msg["contenido"], msg["tipo"])
            for est in sala.estudiantes:
                await est.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        sala.cerrar_sesion(db)
        sala.coordinador = None
        db.close()

# ── WebSocket Estudiante ───────────────────────────────────────
@app.websocket("/ws/estudiante")
async def ws_estudiante(websocket: WebSocket):
    await websocket.accept()
    sala.estudiantes.append(websocket)
    db: Session = SessionLocal()  # ← sesión propia, abierta al conectar

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            sala.guardar_transcripcion(db, msg["contenido"], msg["tipo"])  # ← usa db local
            if sala.coordinador:
                await sala.coordinador.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        sala.estudiantes.remove(websocket)
        db.close()  