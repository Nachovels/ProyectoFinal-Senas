from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session
from app.core.database import engine, Base, SessionLocal
from app.core.auth import verificar_password, crear_token
from app.models import models
from datetime import datetime
import json
import random
import string

Base.metadata.create_all(bind=engine)

app = FastAPI(title="SpeakingHands")

# ── Generador de código ────────────────────────────────────────
def generar_codigo():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# ── Conexiones activas ─────────────────────────────────────────
class SalaManager:
    def __init__(self):
        self.coordinador: WebSocket = None
        self.estudiantes: list[WebSocket] = []
        self.sesion_id: int = None
        self.codigo: str = None

    def iniciar_sesion(self, db: Session, coordinador_id: int = None):
        # Generar código único
        codigo = generar_codigo()
        while db.query(models.Sesion).filter_by(codigo=codigo, finalizada_en=None).first():
            codigo = generar_codigo()

        # Usar coordinador real si viene del login, sino usar demo
        if not coordinador_id:
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
            coordinador_id = coord.id

        sesion = models.Sesion(coordinador_id=coordinador_id, codigo=codigo)
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
        self.sesion_id = sesion.id
        self.codigo = codigo
        return sesion.id, codigo

    def cerrar_sesion(self, db: Session):
        if self.sesion_id:
            sesion = db.query(models.Sesion).filter_by(id=self.sesion_id).first()
            if sesion:
                sesion.finalizada_en = datetime.now()
                db.commit()
        self.sesion_id = None
        self.codigo = None

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
@app.get("/login")
async def login_page():
    with open("../frontend/templates/login.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/coordinador")
async def coordinador_page():
    with open("../frontend/templates/coordinador.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/estudiante")
async def estudiante_page():
    with open("../frontend/templates/estudiante.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# ── API: Login ─────────────────────────────────────────────────
@app.post("/api/login")
async def login(email: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        usuario = db.query(models.Usuario).filter_by(email=email).first()
        if not usuario or not verificar_password(password, usuario.password):
            return JSONResponse(
                status_code=401,
                content={"error": "Credenciales incorrectas"}
            )
        rol = db.query(models.Rol).filter_by(id=usuario.rol_id).first()
        token = crear_token({
            "id": usuario.id,
            "nombre": usuario.nombre,
            "rol": rol.nombre
        })
        return {
            "token": token,
            "nombre": usuario.nombre,
            "rol": rol.nombre
        }
    finally:
        db.close()

# ── API: Crear sala ────────────────────────────────────────────
@app.post("/api/crear-sala")
async def crear_sala():
    db = SessionLocal()
    try:
        sesion_id, codigo = sala.iniciar_sesion(db)
        return {"codigo": codigo, "sesion_id": sesion_id}
    finally:
        db.close()

# ── API: Validar código ────────────────────────────────────────
@app.get("/api/validar-codigo/{codigo}")
async def validar_codigo(codigo: str):
    db = SessionLocal()
    try:
        sesion = db.query(models.Sesion).filter_by(
            codigo=codigo.upper(),
            finalizada_en=None
        ).first()
        if not sesion:
            return JSONResponse(
                status_code=404,
                content={"error": "Código inválido o sesión no encontrada"}
            )
        return {"valido": True, "sesion_id": sesion.id}
    finally:
        db.close()

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

from fastapi import Header, HTTPException, Depends
from typing import Optional
from app.core.auth import extraer_bearer, usuario_desde_token

def requiere_auth(authorization: Optional[str] = Header(None)) -> dict:
    token = extraer_bearer(authorization)
    usuario = usuario_desde_token(token)
    if not usuario:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    return usuario

@app.get("/api/me")
async def me(usuario: dict = Depends(requiere_auth)):
    return {"id": usuario["id"], "nombre": usuario["nombre"], "rol": usuario["rol"]}

@app.get("/api/frases-rapidas")
async def listar_frases(dirigida_a: Optional[str] = None, usuario: dict = Depends(requiere_auth)):
    db = SessionLocal()
    try:
        q = db.query(models.FraseRapida).filter_by(activa=1)
        if dirigida_a in ("coordinador", "estudiante"):
            q = q.filter_by(dirigida_a=dirigida_a)
        frases = q.all()
        return [{"id": f.id, "contenido": f.contenido, "dirigida_a": f.dirigida_a, "categoria": f.categoria} for f in frases]
    finally:
        db.close()        

# ── WebSocket Coordinador ──────────────────────────────────────
@app.websocket("/ws/coordinador")
async def ws_coordinador(websocket: WebSocket):
    await websocket.accept()
    sala.coordinador = websocket
    db: Session = SessionLocal()

    # Si no hay sesión activa, crear una
    if not sala.sesion_id:
        sala.iniciar_sesion(db)

    # Enviar el código al coordinador
    await websocket.send_text(json.dumps({
        "tipo": "codigo_sala",
        "contenido": sala.codigo
    }))

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("tipo") == "ping":
                continue
            sala.guardar_transcripcion(db, msg["contenido"], msg["tipo"])
            for est in sala.estudiantes:
                await est.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        sala.cerrar_sesion(db)
        sala.coordinador = None
        db.close()

# ── WebSocket Estudiante ───────────────────────────────────────
@app.websocket("/ws/estudiante/{codigo}")
async def ws_estudiante(websocket: WebSocket, codigo: str):
    db: Session = SessionLocal()
    sesion = db.query(models.Sesion).filter_by(
        codigo=codigo.upper(),
        finalizada_en=None
    ).first()

    if not sesion:
        await websocket.accept()
        await websocket.close(code=4001)
        db.close()
        return

    await websocket.accept()
    sala.estudiantes.append(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            sala.guardar_transcripcion(db, msg["contenido"], msg["tipo"])
            if sala.coordinador:
                await sala.coordinador.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        sala.estudiantes.remove(websocket)
        db.close()
@app.get("/js/accesibilidad.js")
async def accesibilidad_js():
    with open("../frontend/static/js/accesibilidad.js", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="application/javascript")