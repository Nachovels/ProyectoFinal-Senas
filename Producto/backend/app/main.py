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
    with open("../frontend/js/accesibilidad.js", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="application/javascript")
    # ── Admin: dependencia rol ─────────────────────────────────────
def requiere_rol_admin(usuario: dict = Depends(requiere_auth)):
    if usuario.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    return usuario

# ── Admin: ruta HTML ───────────────────────────────────────────
@app.get("/admin")
async def admin_page():
    with open("../frontend/templates/admin.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# ── Admin: Usuarios ────────────────────────────────────────────
from app.core.auth import hashear_password

@app.get("/api/admin/usuarios")
async def admin_listar_usuarios(admin: dict = Depends(requiere_rol_admin)):
    db = SessionLocal()
    try:
        usuarios = db.query(models.Usuario).order_by(models.Usuario.creado_en.desc()).all()
        roles = {r.id: r.nombre for r in db.query(models.Rol).all()}
        return [{"id": u.id, "nombre": u.nombre, "email": u.email, "rol": roles.get(u.rol_id, "?"),
                 "creado_en": u.creado_en.strftime("%d/%m/%Y %H:%M") if u.creado_en else ""} for u in usuarios]
    finally:
        db.close()

@app.post("/api/admin/usuarios")
async def admin_crear_usuario(
    nombre: str = Form(...), email: str = Form(...),
    password: str = Form(...), rol: str = Form(...),
    admin: dict = Depends(requiere_rol_admin)
):
    db = SessionLocal()
    try:
        if db.query(models.Usuario).filter_by(email=email.strip().lower()).first():
            return JSONResponse(status_code=409, content={"error": "Ya existe una cuenta con ese correo."})
        rol_db = db.query(models.Rol).filter_by(nombre=rol.strip().lower()).first()
        if not rol_db:
            return JSONResponse(status_code=400, content={"error": "Rol no válido."})
        u = models.Usuario(nombre=nombre.strip(), email=email.strip().lower(),
                           password=hashear_password(password), rol_id=rol_db.id)
        db.add(u)
        db.commit()
        db.refresh(u)
        return {"id": u.id, "nombre": u.nombre, "email": u.email, "rol": rol_db.nombre,
                "creado_en": u.creado_en.strftime("%d/%m/%Y %H:%M") if u.creado_en else ""}
    finally:
        db.close()

@app.patch("/api/admin/usuarios/{user_id}/rol")
async def admin_cambiar_rol(user_id: int, rol: str = Form(...), admin: dict = Depends(requiere_rol_admin)):
    db = SessionLocal()
    try:
        u = db.query(models.Usuario).filter_by(id=user_id).first()
        if not u:
            return JSONResponse(status_code=404, content={"error": "Usuario no encontrado."})
        rol_db = db.query(models.Rol).filter_by(nombre=rol.strip().lower()).first()
        if not rol_db:
            return JSONResponse(status_code=400, content={"error": "Rol no válido."})
        u.rol_id = rol_db.id
        db.commit()
        db.refresh(u)
        return {"id": u.id, "nombre": u.nombre, "email": u.email, "rol": rol_db.nombre,
                "creado_en": u.creado_en.strftime("%d/%m/%Y %H:%M") if u.creado_en else ""}
    finally:
        db.close()

@app.delete("/api/admin/usuarios/{user_id}")
async def admin_eliminar_usuario(user_id: int, admin: dict = Depends(requiere_rol_admin)):
    if user_id == admin["id"]:
        return JSONResponse(status_code=400, content={"error": "No puedes eliminar tu propia cuenta."})
    db = SessionLocal()
    try:
        u = db.query(models.Usuario).filter_by(id=user_id).first()
        if not u:
            return JSONResponse(status_code=404, content={"error": "Usuario no encontrado."})
        db.delete(u)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

# ── Admin: Sesiones ────────────────────────────────────────────
@app.get("/api/admin/sesiones")
async def admin_listar_sesiones(estado: Optional[str] = None, admin: dict = Depends(requiere_rol_admin)):
    db = SessionLocal()
    try:
        q = db.query(models.Sesion).order_by(models.Sesion.iniciada_en.desc())
        if estado == "activa":
            q = q.filter(models.Sesion.finalizada_en.is_(None))
        elif estado == "finalizada":
            q = q.filter(models.Sesion.finalizada_en.isnot(None))
        sesiones = q.limit(100).all()
        usuarios = {u.id: u.nombre for u in db.query(models.Usuario).all()}
        counts = {}
        for t in db.query(models.Transcripcion).all():
            counts[t.sesion_id] = counts.get(t.sesion_id, 0) + 1
        return [{
            "id": s.id, "codigo": s.codigo,
            "estado": "activa" if not s.finalizada_en else "finalizada",
            "coordinador": usuarios.get(s.coordinador_id),
            "estudiante": usuarios.get(s.estudiante_id) if s.estudiante_id else None,
            "participantes": [],
            "mensajes": counts.get(s.id, 0),
            "iniciada_en": s.iniciada_en.strftime("%d/%m/%Y %H:%M") if s.iniciada_en else "",
            "finalizada_en": s.finalizada_en.strftime("%d/%m/%Y %H:%M") if s.finalizada_en else None,
        } for s in sesiones]
    finally:
        db.close()

@app.get("/api/admin/sesiones/{sesion_id}")
async def admin_detalle_sesion(sesion_id: int, admin: dict = Depends(requiere_rol_admin)):
    db = SessionLocal()
    try:
        s = db.query(models.Sesion).filter_by(id=sesion_id).first()
        if not s:
            return JSONResponse(status_code=404, content={"error": "Sesión no encontrada."})
        usuarios = {u.id: u.nombre for u in db.query(models.Usuario).all()}
        transcripciones = db.query(models.Transcripcion).filter_by(sesion_id=sesion_id).order_by(models.Transcripcion.creado_en).all()
        return {
            "id": s.id, "codigo": s.codigo,
            "estado": "activa" if not s.finalizada_en else "finalizada",
            "coordinador": usuarios.get(s.coordinador_id),
            "estudiante": usuarios.get(s.estudiante_id) if s.estudiante_id else None,
            "participantes": [],
            "mensajes": len(transcripciones),
            "iniciada_en": s.iniciada_en.strftime("%d/%m/%Y %H:%M") if s.iniciada_en else "",
            "finalizada_en": s.finalizada_en.strftime("%d/%m/%Y %H:%M") if s.finalizada_en else None,
            "transcripciones": [{"id": t.id, "tipo": t.tipo, "contenido": t.contenido,
                "usuario": usuarios.get(t.usuario_id),
                "hora": t.creado_en.strftime("%H:%M") if t.creado_en else "",
                "fecha": t.creado_en.strftime("%d/%m/%Y %H:%M") if t.creado_en else ""} for t in transcripciones]
        }
    finally:
        db.close()

@app.patch("/api/admin/sesiones/{sesion_id}/cerrar")
async def admin_cerrar_sesion(sesion_id: int, admin: dict = Depends(requiere_rol_admin)):
    db = SessionLocal()
    try:
        s = db.query(models.Sesion).filter_by(id=sesion_id).first()
        if not s:
            return JSONResponse(status_code=404, content={"error": "Sesión no encontrada."})
        s.finalizada_en = datetime.now()
        db.commit()
        return {"ok": True, "codigo": s.codigo}
    finally:
        db.close()

@app.delete("/api/admin/sesiones/{sesion_id}")
async def admin_eliminar_sesion(sesion_id: int, admin: dict = Depends(requiere_rol_admin)):
    db = SessionLocal()
    try:
        s = db.query(models.Sesion).filter_by(id=sesion_id).first()
        if not s:
            return JSONResponse(status_code=404, content={"error": "Sesión no encontrada."})
        db.query(models.Transcripcion).filter_by(sesion_id=sesion_id).delete()
        db.delete(s)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.delete("/api/admin/sesiones")
async def admin_eliminar_sesiones_masivo(ids: Optional[str] = None, estado: Optional[str] = None, admin: dict = Depends(requiere_rol_admin)):
    from fastapi import Query as Q
    db = SessionLocal()
    try:
        if ids:
            id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
            sesiones = db.query(models.Sesion).filter(models.Sesion.id.in_(id_list)).all()
        else:
            q = db.query(models.Sesion)
            if estado == "activa":
                q = q.filter(models.Sesion.finalizada_en.is_(None))
            elif estado == "finalizada":
                q = q.filter(models.Sesion.finalizada_en.isnot(None))
            sesiones = q.all()
        for s in sesiones:
            db.query(models.Transcripcion).filter_by(sesion_id=s.id).delete()
            db.delete(s)
        db.commit()
        return {"ok": True, "eliminadas": len(sesiones)}
    finally:
        db.close()

# ── Admin: Frases ──────────────────────────────────────────────
@app.get("/api/admin/frases")
async def admin_listar_frases(admin: dict = Depends(requiere_rol_admin)):
    db = SessionLocal()
    try:
        frases = db.query(models.FraseRapida).order_by(models.FraseRapida.dirigida_a, models.FraseRapida.id).all()
        return [{"id": f.id, "contenido": f.contenido, "dirigida_a": f.dirigida_a,
                 "categoria": f.categoria, "activa": bool(f.activa)} for f in frases]
    finally:
        db.close()

@app.post("/api/admin/frases")
async def admin_crear_frase(
    contenido: str = Form(...), dirigida_a: str = Form(...),
    categoria: str = Form("General"), activa: int = Form(1),
    admin: dict = Depends(requiere_rol_admin)
):
    db = SessionLocal()
    try:
        f = models.FraseRapida(contenido=contenido.strip(), dirigida_a=dirigida_a,
                                categoria=categoria or "General", activa=1 if activa else 0)
        db.add(f)
        db.commit()
        db.refresh(f)
        return {"id": f.id, "contenido": f.contenido, "dirigida_a": f.dirigida_a,
                "categoria": f.categoria, "activa": bool(f.activa)}
    finally:
        db.close()

@app.patch("/api/admin/frases/{frase_id}")
async def admin_editar_frase(
    frase_id: int, contenido: str = Form(...), dirigida_a: str = Form(...),
    categoria: str = Form("General"), activa: int = Form(1),
    admin: dict = Depends(requiere_rol_admin)
):
    db = SessionLocal()
    try:
        f = db.query(models.FraseRapida).filter_by(id=frase_id).first()
        if not f:
            return JSONResponse(status_code=404, content={"error": "Frase no encontrada."})
        f.contenido = contenido.strip()
        f.dirigida_a = dirigida_a
        f.categoria = categoria or "General"
        f.activa = 1 if activa else 0
        db.commit()
        db.refresh(f)
        return {"id": f.id, "contenido": f.contenido, "dirigida_a": f.dirigida_a,
                "categoria": f.categoria, "activa": bool(f.activa)}
    finally:
        db.close()

@app.delete("/api/admin/frases/{frase_id}")
async def admin_eliminar_frase(frase_id: int, admin: dict = Depends(requiere_rol_admin)):
    db = SessionLocal()
    try:
        f = db.query(models.FraseRapida).filter_by(id=frase_id).first()
        if not f:
            return JSONResponse(status_code=404, content={"error": "Frase no encontrada."})
        db.delete(f)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

# ── Admin: Auditoría ───────────────────────────────────────────
@app.get("/api/admin/auditoria")
async def admin_auditoria(accion: Optional[str] = None, admin: dict = Depends(requiere_rol_admin)):
    db = SessionLocal()
    try:
        q = db.query(models.Auditoria).order_by(models.Auditoria.creado_en.desc())
        if accion:
            q = q.filter(models.Auditoria.accion == accion)
        registros = q.limit(100).all()
        usuarios = {u.id: u.nombre for u in db.query(models.Usuario).all()}
        return [{"id": a.id, "accion": a.accion, "detalle": a.detalle or "",
                 "actor": usuarios.get(a.actor_id, "Sistema"),
                 "sesion_id": a.sesion_id,
                 "creado_en": a.creado_en.strftime("%d/%m/%Y %H:%M") if a.creado_en else ""} for a in registros]
    finally:
        db.close()
@app.get("/admin")
async def admin_page():
    with open("../frontend/templates/admin.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())        