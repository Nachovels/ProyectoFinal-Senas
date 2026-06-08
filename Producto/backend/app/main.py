import os
os.environ['CUDA_VISIBLE_DEVICES'] = '-1' # Desactivar GPU por seguridad en backend web

from fastapi import FastAPI, WebSocket, Request
from fastapi.websockets import WebSocketState
from fastapi.templating import Jinja2Templates
import cv2
import numpy as np
import mediapipe as mp
import base64
import time
import json
from tensorflow.keras.models import load_model
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Form, UploadFile, File, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from app.core.database import engine, Base, SessionLocal
from app.core.auth import (
    verificar_password, crear_token, hashear_password,
    extraer_bearer, usuario_desde_token,
)
from app.models import models
from datetime import datetime
import json
import random
import string
import threading

# --- NUEVAS LIBRERÍAS PARA LLM ---
from dotenv import load_dotenv
import google.generativeai as genai

# Cargar clave secreta y configurar Gemini
load_dotenv()
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    llm_model = genai.GenerativeModel('gemini-flash-latest')
    print("API de Gemini configurada con éxito.")
except Exception as e:
    print(f"Error al configurar Gemini: {e}")

app = FastAPI()

# --- CONNECTION MANAGER PARA CHATS ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            if connection.application_state == WebSocketState.CONNECTED:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception as e:
                    print(f"Error enviando mensaje: {e}")

manager = ConnectionManager()

# --- RUTAS DE DIRECTORIOS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES_DIR = os.path.join(BASE_DIR, "frontend", "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

ML_DIR = os.path.join(BASE_DIR, "backend", "ml_pipeline")
DATA_PATH = os.path.join(ML_DIR, 'dataset_sequences')
MODEL_PATH = os.path.join(ML_DIR, 'alphabet_lstm_model.h5')

def _precargar_whisper_al_inicio():
    try:
        from app.voz.transcripcion import precargar_whisper
        resultado = precargar_whisper()
        if resultado.get("ok"):
            print(f"[voz] Whisper listo ({resultado['modelo']}) en {resultado['cache']}")
        else:
            print(f"[voz] Whisper no precargado: {resultado.get('error')}")
    except Exception as exc:
        print(f"[voz] Error al precargar Whisper: {exc}")


@app.on_event("startup")
def startup_precargar_voz():
    _backfill_participantes()
    threading.Thread(target=_precargar_whisper_al_inicio, daemon=True).start()

# ── Dependencias de autenticación ─────────────────────────────
def requiere_auth(authorization: Optional[str] = Header(None)) -> dict:
    token = extraer_bearer(authorization)
    usuario = usuario_desde_token(token)
    if not usuario:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    return usuario

def requiere_rol(rol: str):
    def dependencia(usuario: dict = Depends(requiere_auth)):
        if usuario.get("rol") != rol:
            raise HTTPException(status_code=403, detail="Rol no autorizado")
        return usuario
    return dependencia

# ── Seed de usuarios demo ──────────────────────────────────────
def asegurar_usuarios_demo():
    db = SessionLocal()
    try:
        for nombre_rol in ("admin", "coordinador", "estudiante"):
            if not db.query(models.Rol).filter_by(nombre=nombre_rol).first():
                db.add(models.Rol(nombre=nombre_rol))
        db.commit()

        demos = [
            ("Admin Demo", "admin@demo.cl", "demo", 1),
            ("Coordinador Demo", "coordinador@demo.cl", "demo", 2),
            ("Estudiante Demo", "estudiante@demo.cl", "demo", 3),
        ]
        for nombre, email, pwd, rol_id in demos:
            u = db.query(models.Usuario).filter_by(email=email).first()
            if not u:
                db.add(models.Usuario(
                    nombre=nombre, email=email,
                    password=hashear_password(pwd), rol_id=rol_id,
                ))
            elif not u.password.startswith("$2"):
                u.password = hashear_password(pwd)
        db.commit()
    finally:
        db.close()

asegurar_usuarios_demo()

FRASES_DEMO = [
    ("¿Me entiendes?", "coordinador", "Comprensión"),
    ("¿Está claro?", "coordinador", "Comprensión"),
    ("¿Puedo explicarlo de otra forma?", "coordinador", "Comprensión"),
    ("Te explico de nuevo", "coordinador", "Comprensión"),
    ("Espera un momento", "coordinador", "Ritmo"),
    ("Es tu turno", "coordinador", "Ritmo"),
    ("Un momento por favor", "coordinador", "Ritmo"),
    ("Muy bien", "coordinador", "Ánimo"),
    ("Excelente trabajo", "coordinador", "Ánimo"),
    ("Sigue así", "coordinador", "Ánimo"),
    ("¿Necesitas algo más?", "coordinador", "Apoyo"),
    ("¿Quieres que lo escriba?", "coordinador", "Apoyo"),
    ("Podemos intentar otra forma", "coordinador", "Apoyo"),
    ("No entendí, ¿puede repetir?", "estudiante", "Comprensión"),
    ("¿Puede escribirlo?", "estudiante", "Comprensión"),
    ("No me quedó claro", "estudiante", "Comprensión"),
    ("¿Puede explicarlo de nuevo?", "estudiante", "Comprensión"),
    ("Un momento por favor", "estudiante", "Ritmo"),
    ("Ya estoy listo", "estudiante", "Ritmo"),
    ("Terminé mi parte", "estudiante", "Ritmo"),
    ("Entendí, gracias", "estudiante", "Ánimo"),
    ("Muy bien, gracias", "estudiante", "Ánimo"),
    ("De acuerdo", "estudiante", "Ánimo"),
    ("Tengo una pregunta", "estudiante", "Apoyo"),
    ("Necesito ayuda", "estudiante", "Apoyo"),
    ("¿Cuándo es el plazo?", "estudiante", "Apoyo"),
    ("¿Puede ayudarme?", "estudiante", "Apoyo"),
]

def asegurar_frases_demo():
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE frases_rapidas ADD COLUMN categoria VARCHAR(100) NOT NULL DEFAULT 'General'"
            ))
            conn.commit()
    except Exception:
        pass

    db = SessionLocal()
    try:
        if db.query(models.FraseRapida).count() > 0:
            return
        for contenido, dirigida_a, categoria in FRASES_DEMO:
            db.add(models.FraseRapida(
                contenido=contenido,
                dirigida_a=dirigida_a,
                categoria=categoria,
                activa=1,
            ))
        db.commit()
    finally:
        db.close()

asegurar_frases_demo()

# ── Generador de código ────────────────────────────────────────
def generar_codigo():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def registrar_auditoria(
    db: Session,
    accion: str,
    detalle: str,
    actor_id: int = None,
    usuario_id: int = None,
    sesion_id: int = None,
):
    db.add(models.Auditoria(
        actor_id=actor_id,
        accion=accion,
        detalle=detalle,
        usuario_id=usuario_id,
        sesion_id=sesion_id,
    ))

# ── Conexiones activas (varias salas en paralelo) ───────────────
class SalaActiva:
    def __init__(self, sesion_id: int, codigo: str, coordinador_id: int):
        self.sesion_id = sesion_id
        self.codigo = codigo.upper()
        self.coordinador_id = coordinador_id
        self.coordinador: WebSocket | None = None
        self.estudiantes: dict = {}  # WebSocket -> {"id": int, "nombre": str}


class SalaManager:
    def __init__(self):
        self._por_sesion: dict[int, SalaActiva] = {}
        self._por_codigo: dict[str, int] = {}
        self._ws_coord: dict[WebSocket, int] = {}
        self._ws_est: dict[WebSocket, int] = {}

    def registrar_memoria(self, sesion_id: int, codigo: str, coordinador_id: int) -> SalaActiva:
        sala = SalaActiva(sesion_id, codigo, coordinador_id)
        self._por_sesion[sesion_id] = sala
        self._por_codigo[codigo.upper()] = sesion_id
        return sala

    def ensure_memoria(self, sesion: models.Sesion) -> SalaActiva:
        existente = self._por_sesion.get(sesion.id)
        if existente:
            return existente
        return self.registrar_memoria(sesion.id, sesion.codigo, sesion.coordinador_id)

    def get_sesion(self, sesion_id: int) -> SalaActiva | None:
        return self._por_sesion.get(sesion_id)

    def get_por_codigo(self, codigo: str) -> SalaActiva | None:
        sid = self._por_codigo.get(codigo.upper())
        return self._por_sesion.get(sid) if sid else None

    def sala_en_memoria(self, sesion_id: int) -> bool:
        return sesion_id in self._por_sesion

    def estudiantes_conectados(self, sesion_id: int) -> int:
        sala = self._por_sesion.get(sesion_id)
        return len(sala.estudiantes) if sala else 0

    def iniciar_sesion(self, db: Session, coordinador_id: int):
        codigo = generar_codigo()
        while db.query(models.Sesion).filter_by(codigo=codigo, finalizada_en=None).first():
            codigo = generar_codigo()

        sesion = models.Sesion(coordinador_id=coordinador_id, codigo=codigo)
        db.add(sesion)
        db.commit()
        db.refresh(sesion)
        self.registrar_memoria(sesion.id, sesion.codigo, coordinador_id)
        return sesion.id, codigo

    def reconectar_sesion(self, db: Session, coordinador_id: int, sesion: models.Sesion):
        self.ensure_memoria(sesion)
        return sesion.id, sesion.codigo

    def vincular_coordinador(self, sesion_id: int, websocket: WebSocket) -> SalaActiva | None:
        sala = self._por_sesion.get(sesion_id)
        if not sala:
            return None
        if sala.coordinador and sala.coordinador is not websocket:
            self._ws_coord.pop(sala.coordinador, None)
        sala.coordinador = websocket
        self._ws_coord[websocket] = sesion_id
        return sala

    def vincular_estudiante(
        self, sesion_id: int, websocket: WebSocket, usuario_id: int, nombre: str
    ) -> SalaActiva | None:
        sala = self._por_sesion.get(sesion_id)
        if not sala:
            return None
        sala.estudiantes[websocket] = {"id": usuario_id, "nombre": nombre}
        self._ws_est[websocket] = sesion_id
        return sala

    def desvincular_coordinador(self, websocket: WebSocket):
        sesion_id = self._ws_coord.pop(websocket, None)
        if sesion_id and sesion_id in self._por_sesion:
            sala = self._por_sesion[sesion_id]
            if sala.coordinador is websocket:
                sala.coordinador = None

    def desvincular_estudiante(self, websocket: WebSocket) -> tuple[int | None, dict | None]:
        sesion_id = self._ws_est.pop(websocket, None)
        if not sesion_id or sesion_id not in self._por_sesion:
            return None, None
        info = self._por_sesion[sesion_id].estudiantes.pop(websocket, None)
        return sesion_id, info

    def cerrar_sesion(self, db: Session, actor_id: int = None, sesion_id: int = None):
        sid = sesion_id
        if sid:
            sesion = db.query(models.Sesion).filter_by(id=sid).first()
            if sesion and sesion.finalizada_en is None:
                sesion.finalizada_en = datetime.now()
                registrar_auditoria(
                    db, "cerrar_sala",
                    f"Sesión {sesion.codigo} finalizada",
                    actor_id=actor_id or sesion.coordinador_id,
                    sesion_id=sesion.id,
                )
                db.commit()
        self.eliminar_memoria(sid)

    def eliminar_memoria(self, sesion_id: int):
        sala = self._por_sesion.pop(sesion_id, None)
        if not sala:
            return
        self._por_codigo.pop(sala.codigo, None)
        if sala.coordinador:
            self._ws_coord.pop(sala.coordinador, None)
        for ws in list(sala.estudiantes.keys()):
            self._ws_est.pop(ws, None)

    def guardar_transcripcion(
        self, db: Session, sesion_id: int, contenido: str, tipo: str, usuario_id: int
    ):
        if not sesion_id or not usuario_id:
            return
        db.add(models.Transcripcion(
            sesion_id=sesion_id,
            usuario_id=usuario_id,
            tipo=tipo,
            contenido=contenido,
        ))
        db.commit()


sala = SalaManager()

WS_SESION_TERMINADA = 4004

async def _notificar_sesion_terminada_estudiantes(sesion_id: int, mensaje: str):
    """Avisa a los estudiantes conectados y cierra sus WebSockets."""
    sala_activa = sala.get_sesion(sesion_id)
    if not sala_activa:
        return
    payload = json.dumps({"tipo": "sesion_terminada", "contenido": mensaje})
    for ws in list(sala_activa.estudiantes.keys()):
        try:
            await ws.send_text(payload)
        except Exception:
            pass
        try:
            await ws.close(code=WS_SESION_TERMINADA)
        except Exception:
            pass

# ── Rutas HTML ─────────────────────────────────────────────────
@app.get("/")
async def root():
    return RedirectResponse(url="/login")

@app.get("/login")
async def login_page():
    with open("../frontend/templates/login.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/coordinador")
async def coordinador_page():
    with open("../frontend/templates/coordinador.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# --- CARGAR IA ---
print("Cargando modelo de Visión Artificial (LSTM)...")
model = load_model(MODEL_PATH)
letters = np.array(sorted([f for f in os.listdir(DATA_PATH) if os.path.isdir(os.path.join(DATA_PATH, f))]))
print(f"Modelo cargado. Clases detectadas: {letters}")

# --- UTILIDADES MEDIAPIPE ---
mp_holistic = mp.solutions.holistic

def extract_keypoints(results):
    face_indices = [0, 17, 61, 291, 199, 33, 263, 6, 4, 1, 454, 234, 13, 14, 15, 16, 
                    78, 308, 191, 415, 80, 310, 81, 311, 82, 312, 13, 312, 14, 311, 
                    15, 310, 16, 415, 191, 308, 78, 61, 146, 375, 291, 185, 409, 273, 
                    43, 106, 336, 285]
    pose = np.array([[res.x, res.y, res.z, res.visibility] for res in results.pose_landmarks.landmark]).flatten() if results.pose_landmarks else np.zeros(33*4)
    if results.face_landmarks:
        face = np.array([[results.face_landmarks.landmark[i].x, results.face_landmarks.landmark[i].y, results.face_landmarks.landmark[i].z] for i in face_indices]).flatten()
    else:
        face = np.zeros(len(face_indices)*3)
    if results.left_hand_landmarks:
        lh = np.array([[1.0 - res.x, res.y, res.z] for res in results.left_hand_landmarks.landmark]).flatten()
    else:
        lh = np.zeros(21*3)
    if results.right_hand_landmarks:
        rh = np.array([[res.x, res.y, res.z] for res in results.right_hand_landmarks.landmark]).flatten()
    else:
        rh = np.zeros(21*3)
    return np.concatenate([pose, face, lh, rh])

def normalize_features(frame_data):
    new_data = frame_data.copy()
    if np.any(new_data[0:132]):
        nose_x, nose_y, nose_z = new_data[0], new_data[1], new_data[2]
        for i in range(0, 132, 4):
            new_data[i] -= nose_x
            new_data[i+1] -= nose_y
            new_data[i+2] -= nose_z
        max_val = np.max(np.abs(new_data[0:132]))
        if max_val > 0: new_data[0:132] = new_data[0:132] / max_val
            
    if np.any(new_data[132:276]):
        ref_x, ref_y, ref_z = new_data[132], new_data[133], new_data[134]
        for i in range(132, 276, 3):
            new_data[i] -= ref_x
            new_data[i+1] -= ref_y
            new_data[i+2] -= ref_z
        max_val = np.max(np.abs(new_data[132:276]))
        if max_val > 0: new_data[132:276] = new_data[132:276] / max_val
            
    if np.any(new_data[276:339]):
        wrist_x, wrist_y, wrist_z = new_data[276], new_data[277], new_data[278]
        for i in range(276, 339, 3):
            new_data[i] -= wrist_x
            new_data[i+1] -= wrist_y
            new_data[i+2] -= wrist_z
        max_val = np.max(np.abs(new_data[276:339]))
        if max_val > 0: new_data[276:339] = new_data[276:339] / max_val
            
    if np.any(new_data[339:402]):
        wrist_x, wrist_y, wrist_z = new_data[339], new_data[340], new_data[341]
        for i in range(339, 402, 3):
            new_data[i] -= wrist_x
            new_data[i+1] -= wrist_y
            new_data[i+2] -= wrist_z
        max_val = np.max(np.abs(new_data[339:402]))
        if max_val > 0: new_data[339:402] = new_data[339:402] / max_val
        
    return new_data

# --- FASTAPI RUTAS HTTP ---
@app.get("/estudiante")
async def get_estudiante(request: Request):
    return templates.TemplateResponse(request=request, name="estudiante.html")

@app.get("/index")
async def get_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

# --- FASTAPI RUTAS WEBSOCKET (CHATS) ---
@app.websocket("/ws/estudiante")
async def websocket_estudiante(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(json.loads(data))
    except Exception:
        manager.disconnect(websocket)

@app.websocket("/ws/coordinador")
async def websocket_coordinador(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(json.loads(data))
    except Exception:
        manager.disconnect(websocket)

# --- FASTAPI RUTA WEBSOCKET (IA VIDEO) ---
@app.websocket("/ws/video")
async def websocket_video_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("¡Estudiante conectado al WebSocket con IA y LLM!")
    
    sequence = []
    threshold = 0.8
    frame_counter = 0
    
    # Filtro de Estabilidad (Debounce)
    consecutive_predictions = []
    required_consecutive = 7
    
    # --- VARIABLES PARA EL BUFFER DEL LLM ---
    palabras_buffer = []
    ultima_vez_visto = time.time()
    procesando_llm = False
    
    with mp_holistic.Holistic(min_detection_confidence=0.5, min_tracking_confidence=0.5) as holistic:
        try:
            while True:
                data = await websocket.receive_text()
                
                # --- LÓGICA DEL TEMPORIZADOR PARA LLM ---
                if len(palabras_buffer) > 0 and not procesando_llm:
                    tiempo_inactivo = time.time() - ultima_vez_visto
                    if tiempo_inactivo > 2.5: 
                        procesando_llm = True
                        await websocket.send_text(f"✍️ TRADUCIENDO FRASE: {' '.join(palabras_buffer)}...")
                        
                        prompt = f"Eres un intérprete de lengua de señas en una universidad de Chile. Toma estas palabras sueltas detectadas por visión artificial y arma una oración gramaticalmente correcta, natural y formal en español. Solo entrega la oración final, nada de explicaciones extras. Palabras: {', '.join(palabras_buffer)}"
                        
                        try:
                            respuesta = llm_model.generate_content(prompt)
                            frase_final = respuesta.text.strip()
                            
                            # 1. Enviar a la vista del estudiante (cuadro verde)
                            await websocket.send_text(f"✅ TRADUCCIÓN FINAL: {frase_final}")
                            
                            # 2. EMITIR AL COORDINADOR COMO MENSAJE DE CHAT
                            mensaje_chat = {
                                "tipo": "estudiante",
                                "contenido": frase_final
                            }
                            await manager.broadcast(mensaje_chat)
                            
                        except Exception as e:
                            await websocket.send_text(f"❌ Error en la traducción LLM.")
                            print(f"Error Gemini: {e}")
                            
                        # Limpiar buffer para la siguiente oración
                        palabras_buffer = []
                        procesando_llm = False
                
                # 2. Decodificar a OpenCV (solo si no estamos pausados esperando al LLM)
                if not procesando_llm:
                    encoded_data = data.split(',')[1]
                    nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    
                    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    results = holistic.process(image_rgb)
                    
                    keypoints = extract_keypoints(results)
                    keypoints = normalize_features(keypoints)
                    
                    # 3. Lógica de Predicción LSTM
                    if np.any(keypoints[-126:] != 0):
                        sequence.append(keypoints)
                        sequence = sequence[-30:] 
                        frame_counter += 1
                        ultima_vez_visto = time.time() # Reiniciar el cronómetro porque vimos manos
                        
                        if len(sequence) == 30 and frame_counter % 3 == 0:
                            res = model.predict(np.expand_dims(sequence, axis=0), verbose=0)[0]
                            prediction_idx = np.argmax(res)
                            confidence = res[prediction_idx]
                            
                            if confidence > threshold:
                                current_prediction = letters[prediction_idx]
                                consecutive_predictions.append(current_prediction)
                                consecutive_predictions = consecutive_predictions[-required_consecutive:]
                                
                                if len(consecutive_predictions) == required_consecutive and all(p == current_prediction for p in consecutive_predictions):
                                    # Si la seña es estable y diferente de Z_NADA
                                    if current_prediction != "Z_NADA":
                                        # Agregamos al buffer solo si es una palabra nueva (evita "HOLA HOLA HOLA")
                                        if len(palabras_buffer) == 0 or palabras_buffer[-1] != current_prediction:
                                            palabras_buffer.append(current_prediction)
                                            await websocket.send_text(f"👁️ Detectado: {' '.join(palabras_buffer)}")
                            else:
                                consecutive_predictions = []
                    else:
                        sequence = [] 
                        consecutive_predictions = []
                        if len(palabras_buffer) == 0:
                            await websocket.send_text("ESPERANDO SEÑAS...")
                        
        except Exception as e:
            print(f"Desconectado o Error en Video: {e}")
async def estudiante_page():
    with open("../frontend/templates/estudiante.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/admin")
async def admin_page():
    with open("../frontend/templates/admin.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/js/voz-sesion.js")
async def voz_sesion_js():
    with open("../frontend/js/voz-sesion.js", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="application/javascript")

@app.get("/js/accesibilidad.js")
async def accesibilidad_js():
    with open("../frontend/js/accesibilidad.js", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="application/javascript")

@app.get("/css/accesibilidad.css")
async def accesibilidad_css():
    with open("../frontend/css/accesibilidad.css", encoding="utf-8") as f:
        return Response(content=f.read(), media_type="text/css")

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
            "id": usuario.id,
            "nombre": usuario.nombre,
            "rol": rol.nombre
        }
    finally:
        db.close()

# Registro público: solo estudiante (coordinador lo asigna el admin)
ROLES_ASIGNABLES = ("estudiante", "coordinador", "admin")

@app.post("/api/registro")
async def registro(
    nombre: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    nombre = nombre.strip()
    email = email.strip().lower()
    rol = "estudiante"

    if len(nombre) < 2:
        return JSONResponse(status_code=400, content={"error": "El nombre debe tener al menos 2 caracteres."})
    if len(password) < 4:
        return JSONResponse(status_code=400, content={"error": "La contraseña debe tener al menos 4 caracteres."})

    db = SessionLocal()
    try:
        if db.query(models.Usuario).filter_by(email=email).first():
            return JSONResponse(status_code=409, content={"error": "Ya existe una cuenta con ese correo."})

        rol_db = db.query(models.Rol).filter_by(nombre=rol).first()
        if not rol_db:
            return JSONResponse(status_code=400, content={"error": "Rol no disponible en el sistema."})

        usuario = models.Usuario(
            nombre=nombre,
            email=email,
            password=hashear_password(password),
            rol_id=rol_db.id,
        )
        db.add(usuario)
        db.commit()
        db.refresh(usuario)

        registrar_auditoria(
            db, "registro_usuario",
            f"Nuevo estudiante: {usuario.nombre} ({usuario.email})",
            actor_id=usuario.id, usuario_id=usuario.id,
        )
        db.commit()

        token = crear_token({
            "id": usuario.id,
            "nombre": usuario.nombre,
            "rol": rol_db.nombre,
        })
        return {
            "token": token,
            "id": usuario.id,
            "nombre": usuario.nombre,
            "rol": rol_db.nombre,
        }
    finally:
        db.close()

# ── API: Administración de usuarios ───────────────────────────
def _mapa_usuarios(db: Session) -> dict:
    return {u.id: u for u in db.query(models.Usuario).all()}

def _nombre_usuario(u: models.Usuario | None) -> str | None:
    if not u:
        return None
    return u.nombre

def _enriquecer_msg_ws(msg: dict, nombre: str, usuario_id: int, remitente_rol: str) -> dict:
    out = dict(msg)
    out["nombre"] = nombre
    out["usuario_id"] = usuario_id
    out["remitente_rol"] = remitente_rol
    return out

def _es_estudiante_en_sesion(db: Session, sesion: models.Sesion | None, usuario_id: int) -> bool:
    if not sesion or not usuario_id:
        return False
    if usuario_id == sesion.coordinador_id:
        return False
    usuario = db.query(models.Usuario).filter_by(id=usuario_id).first()
    if not usuario:
        return False
    rol = db.query(models.Rol).filter_by(id=usuario.rol_id).first()
    return bool(rol and rol.nombre == "estudiante")

def _registrar_participante(db: Session, sesion_id: int, usuario_id: int):
    sesion = db.query(models.Sesion).filter_by(id=sesion_id).first()
    if not _es_estudiante_en_sesion(db, sesion, usuario_id):
        return
    existe = db.query(models.SesionParticipante).filter_by(
        sesion_id=sesion_id, usuario_id=usuario_id
    ).first()
    if not existe:
        db.add(models.SesionParticipante(sesion_id=sesion_id, usuario_id=usuario_id))

def _participantes_estudiantes(db: Session, sesion_id: int) -> list[dict]:
    sesion = db.query(models.Sesion).filter_by(id=sesion_id).first()
    if not sesion:
        return []
    usuarios = _mapa_usuarios(db)
    filas = db.query(models.SesionParticipante).filter_by(sesion_id=sesion_id).all()
    vistos: set[int] = set()
    resultado: list[dict] = []

    for p in filas:
        if not _es_estudiante_en_sesion(db, sesion, p.usuario_id):
            continue
        if p.usuario_id in vistos:
            continue
        nombre = _nombre_usuario(usuarios.get(p.usuario_id))
        if not nombre:
            continue
        vistos.add(p.usuario_id)
        resultado.append({"id": p.usuario_id, "nombre": nombre})

    if not resultado and sesion.estudiante_id and _es_estudiante_en_sesion(db, sesion, sesion.estudiante_id):
        u = usuarios.get(sesion.estudiante_id)
        nombre = _nombre_usuario(u)
        if nombre:
            resultado.append({"id": sesion.estudiante_id, "nombre": nombre})
    return resultado

def _nombres_participantes(db: Session, sesion_id: int) -> list[str]:
    return [p["nombre"] for p in _participantes_estudiantes(db, sesion_id)]

def _limpiar_participantes_invalidos(db: Session):
    sesiones = db.query(models.Sesion).all()
    for s in sesiones:
        filas = db.query(models.SesionParticipante).filter_by(sesion_id=s.id).all()
        for p in filas:
            if not _es_estudiante_en_sesion(db, s, p.usuario_id):
                db.delete(p)

def _info_estudiantes_sesion(db: Session, sesion_id: int) -> dict:
    participantes = _participantes_estudiantes(db, sesion_id)
    nombres = [p["nombre"] for p in participantes]
    return {
        "estudiantes": participantes,
        "estudiantes_nombres": nombres,
        "participantes_count": len(participantes),
        "estudiantes_conectados": sala.estudiantes_conectados(sesion_id),
    }

def _backfill_participantes():
    db = SessionLocal()
    try:
        sesiones = db.query(models.Sesion).filter(models.Sesion.estudiante_id.isnot(None)).all()
        for s in sesiones:
            if _es_estudiante_en_sesion(db, s, s.estudiante_id):
                _registrar_participante(db, s.id, s.estudiante_id)
        _limpiar_participantes_invalidos(db)
        db.commit()
    except Exception as exc:
        print(f"[sesiones] Backfill participantes: {exc}")
    finally:
        db.close()

def _serializar_usuario(u: models.Usuario, rol_nombre: str) -> dict:
    return {
        "id": u.id,
        "nombre": u.nombre,
        "email": u.email,
        "rol": rol_nombre,
        "creado_en": u.creado_en.strftime("%d/%m/%Y %H:%M") if u.creado_en else "",
    }

def _serializar_sesion(s, usuarios: dict, mensajes: int = 0, db: Session | None = None) -> dict:
    coord = usuarios.get(s.coordinador_id)
    est = usuarios.get(s.estudiante_id) if s.estudiante_id else None
    participantes = _nombres_participantes(db, s.id) if db else []
    return {
        "id": s.id,
        "codigo": s.codigo,
        "estado": "activa" if s.finalizada_en is None else "finalizada",
        "coordinador_id": s.coordinador_id,
        "coordinador": _nombre_usuario(coord),
        "estudiante_id": s.estudiante_id,
        "estudiante": _nombre_usuario(est),
        "participantes": participantes,
        "participantes_count": len(participantes),
        "estudiantes_conectados": sala.estudiantes_conectados(s.id),
        "iniciada_en": s.iniciada_en.strftime("%d/%m/%Y %H:%M") if s.iniciada_en else "",
        "finalizada_en": s.finalizada_en.strftime("%d/%m/%Y %H:%M") if s.finalizada_en else None,
        "mensajes": mensajes,
    }

def _serializar_auditoria(a: models.Auditoria, usuarios: dict) -> dict:
    actor = usuarios.get(a.actor_id) if a.actor_id else None
    afectado = usuarios.get(a.usuario_id) if a.usuario_id else None
    return {
        "id": a.id,
        "accion": a.accion,
        "detalle": a.detalle or "",
        "actor": _nombre_usuario(actor) or "Sistema",
        "usuario_afectado": _nombre_usuario(afectado),
        "sesion_id": a.sesion_id,
        "creado_en": a.creado_en.strftime("%d/%m/%Y %H:%M") if a.creado_en else "",
    }

def _limpiar_sala_memoria(sesion_id: int):
    sala.eliminar_memoria(sesion_id)

def _eliminar_sesion_db(db: Session, sesion: models.Sesion):
    sid = sesion.id
    db.query(models.SesionParticipante).filter_by(sesion_id=sid).delete(synchronize_session=False)
    db.query(models.Transcripcion).filter_by(sesion_id=sid).delete(synchronize_session=False)
    db.query(models.RegistroIA).filter_by(sesion_id=sid).delete(synchronize_session=False)
    db.query(models.Auditoria).filter_by(sesion_id=sid).update(
        {models.Auditoria.sesion_id: None}, synchronize_session=False
    )
    db.flush()
    db.delete(sesion)
    db.flush()
    _limpiar_sala_memoria(sid)

def _eliminar_usuario_db(db: Session, usuario: models.Usuario):
    uid = usuario.id
    sesiones_coord = db.query(models.Sesion).filter_by(coordinador_id=uid).all()
    for sesion in sesiones_coord:
        _eliminar_sesion_db(db, sesion)
    db.query(models.Sesion).filter_by(estudiante_id=uid).update(
        {models.Sesion.estudiante_id: None}, synchronize_session=False
    )
    db.query(models.SesionParticipante).filter_by(usuario_id=uid).delete(synchronize_session=False)
    db.query(models.Transcripcion).filter_by(usuario_id=uid).delete(synchronize_session=False)
    db.query(models.Auditoria).filter_by(actor_id=uid).update(
        {models.Auditoria.actor_id: None}, synchronize_session=False
    )
    db.query(models.Auditoria).filter_by(usuario_id=uid).update(
        {models.Auditoria.usuario_id: None}, synchronize_session=False
    )
    db.flush()
    db.delete(usuario)
    db.flush()

@app.get("/api/admin/usuarios")
async def listar_usuarios(admin: dict = Depends(requiere_rol("admin"))):
    db = SessionLocal()
    try:
        usuarios = db.query(models.Usuario).order_by(models.Usuario.creado_en.desc()).all()
        roles = {r.id: r.nombre for r in db.query(models.Rol).all()}
        return [_serializar_usuario(u, roles.get(u.rol_id, "?")) for u in usuarios]
    finally:
        db.close()

@app.post("/api/admin/usuarios")
async def crear_usuario_admin(
    nombre: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    rol: str = Form(...),
    admin: dict = Depends(requiere_rol("admin")),
):
    nombre = nombre.strip()
    email = email.strip().lower()
    rol = rol.strip().lower()

    if len(nombre) < 2:
        return JSONResponse(status_code=400, content={"error": "El nombre debe tener al menos 2 caracteres."})
    if len(password) < 4:
        return JSONResponse(status_code=400, content={"error": "La contraseña debe tener al menos 4 caracteres."})
    if rol not in ROLES_ASIGNABLES:
        return JSONResponse(status_code=400, content={"error": "Rol no válido."})

    db = SessionLocal()
    try:
        if db.query(models.Usuario).filter_by(email=email).first():
            return JSONResponse(status_code=409, content={"error": "Ya existe una cuenta con ese correo."})

        rol_db = db.query(models.Rol).filter_by(nombre=rol).first()
        if not rol_db:
            return JSONResponse(status_code=400, content={"error": "Rol no disponible."})

        usuario = models.Usuario(
            nombre=nombre,
            email=email,
            password=hashear_password(password),
            rol_id=rol_db.id,
        )
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
        registrar_auditoria(
            db, "admin_crear_usuario",
            f"Usuario creado como {rol_db.nombre}: {usuario.nombre} ({usuario.email})",
            actor_id=admin["id"], usuario_id=usuario.id,
        )
        db.commit()
        return _serializar_usuario(usuario, rol_db.nombre)
    finally:
        db.close()

@app.patch("/api/admin/usuarios/{user_id}/rol")
async def cambiar_rol_usuario(
    user_id: int,
    rol: str = Form(...),
    admin: dict = Depends(requiere_rol("admin")),
):
    rol = rol.strip().lower()
    if rol not in ROLES_ASIGNABLES:
        return JSONResponse(status_code=400, content={"error": "Rol no válido."})
    if user_id == admin["id"]:
        return JSONResponse(status_code=400, content={"error": "No puedes cambiar tu propio rol."})

    db = SessionLocal()
    try:
        usuario = db.query(models.Usuario).filter_by(id=user_id).first()
        if not usuario:
            return JSONResponse(status_code=404, content={"error": "Usuario no encontrado."})

        rol_actual = db.query(models.Rol).filter_by(id=usuario.rol_id).first()
        rol_nuevo = db.query(models.Rol).filter_by(nombre=rol).first()
        if not rol_nuevo:
            return JSONResponse(status_code=400, content={"error": "Rol no disponible."})

        if rol_actual and rol_actual.nombre == "admin" and rol != "admin":
            admins = db.query(models.Usuario).join(models.Rol).filter(models.Rol.nombre == "admin").count()
            if admins <= 1:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Debe existir al menos un administrador."},
                )

        usuario.rol_id = rol_nuevo.id
        registrar_auditoria(
            db, "admin_cambio_rol",
            f"Rol cambiado de {rol_actual.nombre if rol_actual else '?'} a {rol_nuevo.nombre} para {usuario.nombre}",
            actor_id=admin["id"], usuario_id=usuario.id,
        )
        db.commit()
        db.refresh(usuario)
        return _serializar_usuario(usuario, rol_nuevo.nombre)
    finally:
        db.close()

@app.delete("/api/admin/usuarios/{user_id}")
async def eliminar_usuario(
    user_id: int,
    admin: dict = Depends(requiere_rol("admin")),
):
    if user_id == admin["id"]:
        return JSONResponse(status_code=400, content={"error": "No puedes eliminar tu propia cuenta."})

    db = SessionLocal()
    try:
        usuario = db.query(models.Usuario).filter_by(id=user_id).first()
        if not usuario:
            return JSONResponse(status_code=404, content={"error": "Usuario no encontrado."})

        rol = db.query(models.Rol).filter_by(id=usuario.rol_id).first()
        if rol and rol.nombre == "admin":
            admins = db.query(models.Usuario).join(models.Rol).filter(models.Rol.nombre == "admin").count()
            if admins <= 1:
                return JSONResponse(
                    status_code=400,
                    content={"error": "No se puede eliminar al único administrador."},
                )

        sesiones_activas = db.query(models.Sesion).filter(
            models.Sesion.coordinador_id == user_id,
            models.Sesion.finalizada_en.is_(None),
        ).all()
        for s in sesiones_activas:
            await _notificar_sesion_terminada_estudiantes(
                s.id, "La sesión fue cerrada porque el coordinador fue eliminado."
            )

        registrar_auditoria(
            db, "admin_eliminar_usuario",
            f"Usuario eliminado: {usuario.nombre} ({usuario.email})",
            actor_id=admin["id"], usuario_id=None,
        )
        _eliminar_usuario_db(db, usuario)
        db.commit()
        return {"ok": True}
    except Exception as exc:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": f"No se pudo eliminar: {exc}"})
    finally:
        db.close()

# ── API: Administración de salas ──────────────────────────────
@app.get("/api/admin/sesiones")
async def listar_sesiones(
    estado: Optional[str] = Query(None),
    admin: dict = Depends(requiere_rol("admin")),
):
    db = SessionLocal()
    try:
        q = db.query(models.Sesion).order_by(models.Sesion.iniciada_en.desc())
        if estado == "activa":
            q = q.filter(models.Sesion.finalizada_en.is_(None))
        elif estado == "finalizada":
            q = q.filter(models.Sesion.finalizada_en.isnot(None))

        sesiones = q.limit(100).all()
        usuarios = _mapa_usuarios(db)
        counts = {}
        for t in db.query(models.Transcripcion).all():
            counts[t.sesion_id] = counts.get(t.sesion_id, 0) + 1

        return [_serializar_sesion(s, usuarios, counts.get(s.id, 0), db=db) for s in sesiones]
    finally:
        db.close()

@app.get("/api/admin/sesiones/{sesion_id}")
async def detalle_sesion(
    sesion_id: int,
    admin: dict = Depends(requiere_rol("admin")),
):
    db = SessionLocal()
    try:
        sesion = db.query(models.Sesion).filter_by(id=sesion_id).first()
        if not sesion:
            return JSONResponse(status_code=404, content={"error": "Sesión no encontrada."})

        usuarios = _mapa_usuarios(db)
        transcripciones = (
            db.query(models.Transcripcion)
            .filter_by(sesion_id=sesion_id)
            .order_by(models.Transcripcion.creado_en)
            .all()
        )
        data = _serializar_sesion(sesion, usuarios, len(transcripciones), db=db)
        data["transcripciones"] = [
            {
                "id": t.id,
                "tipo": t.tipo,
                "contenido": t.contenido,
                "usuario": _nombre_usuario(usuarios.get(t.usuario_id)),
                "hora": t.creado_en.strftime("%H:%M") if t.creado_en else "",
                "fecha": t.creado_en.strftime("%d/%m/%Y %H:%M") if t.creado_en else "",
            }
            for t in transcripciones
        ]
        return data
    finally:
        db.close()

@app.patch("/api/admin/sesiones/{sesion_id}/cerrar")
async def admin_cerrar_sesion(
    sesion_id: int,
    admin: dict = Depends(requiere_rol("admin")),
):
    db = SessionLocal()
    try:
        sesion = db.query(models.Sesion).filter_by(id=sesion_id).first()
        if not sesion:
            return JSONResponse(status_code=404, content={"error": "Sesión no encontrada."})
        if sesion.finalizada_en:
            return JSONResponse(status_code=400, content={"error": "La sesión ya está finalizada."})

        sesion.finalizada_en = datetime.now()
        registrar_auditoria(
            db, "admin_cerrar_sala",
            f"Sesión {sesion.codigo} cerrada por administrador",
            actor_id=admin["id"], sesion_id=sesion.id,
        )
        db.commit()
        await _notificar_sesion_terminada_estudiantes(
            sesion_id, "El administrador cerró la sesión."
        )
        _limpiar_sala_memoria(sesion_id)
        usuarios = _mapa_usuarios(db)
        return _serializar_sesion(sesion, usuarios, db=db)
    finally:
        db.close()

@app.delete("/api/admin/sesiones/{sesion_id}")
async def admin_eliminar_sesion(
    sesion_id: int,
    admin: dict = Depends(requiere_rol("admin")),
):
    db = SessionLocal()
    try:
        sesion = db.query(models.Sesion).filter_by(id=sesion_id).first()
        if not sesion:
            return JSONResponse(status_code=404, content={"error": "Sesión no encontrada."})

        codigo = sesion.codigo
        if sesion.finalizada_en is None:
            await _notificar_sesion_terminada_estudiantes(
                sesion_id, "La sesión fue eliminada por el administrador."
            )
        registrar_auditoria(
            db, "admin_eliminar_sala",
            f"Sesión {codigo} eliminada con todos sus registros",
            actor_id=admin["id"], sesion_id=None,
        )
        _eliminar_sesion_db(db, sesion)
        db.commit()
        return {"ok": True}
    except Exception as exc:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": f"No se pudo eliminar: {exc}"})
    finally:
        db.close()

@app.delete("/api/admin/sesiones")
async def admin_eliminar_sesiones_masivo(
    estado: Optional[str] = Query(None),
    ids: Optional[str] = Query(None),
    admin: dict = Depends(requiere_rol("admin")),
):
    """Elimina varias salas. Usar ids=1,2,3 o estado=activa|finalizada."""
    db = SessionLocal()
    try:
        if ids:
            id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
            if not id_list:
                return JSONResponse(status_code=400, content={"error": "IDs inválidos."})
            sesiones = db.query(models.Sesion).filter(models.Sesion.id.in_(id_list)).all()
        else:
            q = db.query(models.Sesion)
            if estado == "activa":
                q = q.filter(models.Sesion.finalizada_en.is_(None))
            elif estado == "finalizada":
                q = q.filter(models.Sesion.finalizada_en.isnot(None))
            sesiones = q.all()

        if not sesiones:
            return JSONResponse(status_code=404, content={"error": "No hay salas para eliminar."})

        for s in sesiones:
            if s.finalizada_en is None:
                await _notificar_sesion_terminada_estudiantes(
                    s.id, "La sesión fue eliminada por el administrador."
                )

        eliminadas = 0
        for s in sesiones:
            registrar_auditoria(
                db, "admin_eliminar_sala",
                f"Sesión {s.codigo} (id {s.id}) eliminada (borrado masivo)",
                actor_id=admin["id"], sesion_id=None,
            )
            _eliminar_sesion_db(db, s)
            eliminadas += 1

        db.commit()
        return {"ok": True, "eliminadas": eliminadas}
    except Exception as exc:
        db.rollback()
        return JSONResponse(status_code=500, content={"error": f"No se pudo eliminar: {exc}"})
    finally:
        db.close()

# ── API: Auditoría ─────────────────────────────────────────────
@app.get("/api/admin/auditoria")
async def listar_auditoria(
    accion: Optional[str] = Query(None),
    limite: int = Query(100, le=500),
    admin: dict = Depends(requiere_rol("admin")),
):
    db = SessionLocal()
    try:
        q = db.query(models.Auditoria).order_by(models.Auditoria.creado_en.desc())
        if accion:
            q = q.filter(models.Auditoria.accion == accion)
        registros = q.limit(limite).all()
        usuarios = _mapa_usuarios(db)
        return [_serializar_auditoria(a, usuarios) for a in registros]
    finally:
        db.close()

# ── API: Frases rápidas (público autenticado) ─────────────────
def _serializar_frase(f: models.FraseRapida) -> dict:
    return {
        "id": f.id,
        "contenido": f.contenido,
        "dirigida_a": f.dirigida_a,
        "categoria": f.categoria or "General",
        "activa": bool(f.activa),
    }

@app.get("/api/frases-rapidas")
async def listar_frases_publicas(
    dirigida_a: Optional[str] = Query(None),
    usuario: dict = Depends(requiere_auth),
):
    db = SessionLocal()
    try:
        q = db.query(models.FraseRapida).filter_by(activa=1)
        if dirigida_a in ("coordinador", "estudiante"):
            q = q.filter_by(dirigida_a=dirigida_a)
        frases = q.order_by(models.FraseRapida.categoria, models.FraseRapida.id).all()
        return [_serializar_frase(f) for f in frases]
    finally:
        db.close()

# ── API: Admin frases rápidas ──────────────────────────────────
@app.get("/api/admin/frases")
async def admin_listar_frases(
    dirigida_a: Optional[str] = Query(None),
    admin: dict = Depends(requiere_rol("admin")),
):
    db = SessionLocal()
    try:
        q = db.query(models.FraseRapida).order_by(
            models.FraseRapida.dirigida_a,
            models.FraseRapida.categoria,
            models.FraseRapida.id,
        )
        if dirigida_a in ("coordinador", "estudiante"):
            q = q.filter_by(dirigida_a=dirigida_a)
        return [_serializar_frase(f) for f in q.all()]
    finally:
        db.close()

@app.post("/api/admin/frases")
async def admin_crear_frase(
    contenido: str = Form(...),
    dirigida_a: str = Form(...),
    categoria: str = Form("General"),
    activa: int = Form(1),
    admin: dict = Depends(requiere_rol("admin")),
):
    contenido = contenido.strip()
    dirigida_a = dirigida_a.strip().lower()
    categoria = categoria.strip() or "General"

    if len(contenido) < 2:
        return JSONResponse(status_code=400, content={"error": "La frase debe tener al menos 2 caracteres."})
    if len(contenido) > 255:
        return JSONResponse(status_code=400, content={"error": "La frase no puede superar 255 caracteres."})
    if dirigida_a not in ("coordinador", "estudiante"):
        return JSONResponse(status_code=400, content={"error": "Dirigida a debe ser coordinador o estudiante."})

    db = SessionLocal()
    try:
        frase = models.FraseRapida(
            contenido=contenido,
            dirigida_a=dirigida_a,
            categoria=categoria,
            activa=1 if activa else 0,
        )
        db.add(frase)
        registrar_auditoria(
            db, "admin_crear_frase",
            f"Frase creada ({dirigida_a}): {contenido}",
            actor_id=admin["id"],
        )
        db.commit()
        db.refresh(frase)
        return _serializar_frase(frase)
    finally:
        db.close()

@app.patch("/api/admin/frases/{frase_id}")
async def admin_editar_frase(
    frase_id: int,
    contenido: str = Form(...),
    dirigida_a: str = Form(...),
    categoria: str = Form("General"),
    activa: int = Form(1),
    admin: dict = Depends(requiere_rol("admin")),
):
    contenido = contenido.strip()
    dirigida_a = dirigida_a.strip().lower()
    categoria = categoria.strip() or "General"

    if len(contenido) < 2:
        return JSONResponse(status_code=400, content={"error": "La frase debe tener al menos 2 caracteres."})
    if dirigida_a not in ("coordinador", "estudiante"):
        return JSONResponse(status_code=400, content={"error": "Dirigida a debe ser coordinador o estudiante."})

    db = SessionLocal()
    try:
        frase = db.query(models.FraseRapida).filter_by(id=frase_id).first()
        if not frase:
            return JSONResponse(status_code=404, content={"error": "Frase no encontrada."})

        frase.contenido = contenido
        frase.dirigida_a = dirigida_a
        frase.categoria = categoria
        frase.activa = 1 if activa else 0
        registrar_auditoria(
            db, "admin_editar_frase",
            f"Frase #{frase_id} actualizada: {contenido}",
            actor_id=admin["id"],
        )
        db.commit()
        db.refresh(frase)
        return _serializar_frase(frase)
    finally:
        db.close()

@app.delete("/api/admin/frases/{frase_id}")
async def admin_eliminar_frase(
    frase_id: int,
    admin: dict = Depends(requiere_rol("admin")),
):
    db = SessionLocal()
    try:
        frase = db.query(models.FraseRapida).filter_by(id=frase_id).first()
        if not frase:
            return JSONResponse(status_code=404, content={"error": "Frase no encontrada."})

        texto = frase.contenido
        registrar_auditoria(
            db, "admin_eliminar_frase",
            f"Frase eliminada: {texto}",
            actor_id=admin["id"],
        )
        db.delete(frase)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.get("/api/me")
async def me(usuario: dict = Depends(requiere_auth)):
    return {"id": usuario["id"], "nombre": usuario["nombre"], "rol": usuario["rol"]}

# ── API: Crear sala ────────────────────────────────────────────
@app.post("/api/crear-sala")
async def crear_sala(usuario: dict = Depends(requiere_rol("coordinador"))):
    db = SessionLocal()
    try:
        sesion_id, codigo = sala.iniciar_sesion(db, usuario["id"])
        registrar_auditoria(
            db, "crear_sala",
            f"Sala {codigo} creada",
            actor_id=usuario["id"], sesion_id=sesion_id,
        )
        db.commit()
        info = _info_estudiantes_sesion(db, sesion_id)
        return {
            "codigo": codigo,
            "sesion_id": sesion_id,
            "estudiante_nombre": info["estudiantes_nombres"][0] if info["estudiantes_nombres"] else None,
            **info,
        }
    finally:
        db.close()

@app.get("/api/mis-salas-activas")
async def mis_salas_activas(usuario: dict = Depends(requiere_rol("coordinador"))):
    db = SessionLocal()
    try:
        sesiones = (
            db.query(models.Sesion)
            .filter_by(coordinador_id=usuario["id"], finalizada_en=None)
            .order_by(models.Sesion.iniciada_en.desc())
            .all()
        )
        usuarios = _mapa_usuarios(db)
        return [
            {
                "sesion_id": s.id,
                "codigo": s.codigo,
                "iniciada_en": s.iniciada_en.strftime("%d/%m/%Y %H:%M") if s.iniciada_en else "",
                "estudiante_asignado": s.estudiante_id is not None,
                "estudiante_nombre": _nombre_usuario(usuarios.get(s.estudiante_id)),
                "en_memoria": sala.sala_en_memoria(s.id),
                **_info_estudiantes_sesion(db, s.id),
            }
            for s in sesiones
        ]
    finally:
        db.close()

@app.post("/api/unirse-sala-coordinador")
async def unirse_sala_coordinador(
    codigo: str = Form(...),
    usuario: dict = Depends(requiere_rol("coordinador")),
):
    db = SessionLocal()
    try:
        codigo = codigo.strip().upper()
        if len(codigo) != 6:
            return JSONResponse(status_code=400, content={"error": "El código debe tener 6 caracteres."})

        sesion = db.query(models.Sesion).filter_by(
            codigo=codigo,
            coordinador_id=usuario["id"],
            finalizada_en=None,
        ).first()
        if not sesion:
            return JSONResponse(
                status_code=404,
                content={"error": "Sala no encontrada, ya finalizada o no te pertenece."},
            )

        sesion_id, codigo_ok = sala.reconectar_sesion(db, usuario["id"], sesion)
        registrar_auditoria(
            db, "reconectar_sala",
            f"Coordinador reconectado a sala {codigo_ok}",
            actor_id=usuario["id"], sesion_id=sesion_id,
        )
        db.commit()
        info = _info_estudiantes_sesion(db, sesion_id)
        return {
            "codigo": codigo_ok,
            "sesion_id": sesion_id,
            "reconexion": True,
            "estudiante_nombre": info["estudiantes_nombres"][0] if info["estudiantes_nombres"] else None,
            **info,
        }
    finally:
        db.close()

@app.post("/api/cerrar-sala")
async def cerrar_sala_coordinador(
    sesion_id: Optional[int] = Form(None),
    usuario: dict = Depends(requiere_rol("coordinador")),
):
    db = SessionLocal()
    try:
        sid = sesion_id
        if not sid:
            return JSONResponse(status_code=400, content={"error": "Indica sesion_id para cerrar la sala."})

        sesion = db.query(models.Sesion).filter_by(
            id=sid,
            coordinador_id=usuario["id"],
            finalizada_en=None,
        ).first()
        if not sesion:
            return JSONResponse(status_code=404, content={"error": "Sesión no encontrada o ya finalizada."})

        codigo = sesion.codigo
        sala_activa = sala.get_sesion(sid)
        if sala_activa:
            await _notificar_sesion_terminada_estudiantes(
                sid, "El coordinador finalizó la sesión."
            )
            if sala_activa.coordinador:
                try:
                    await sala_activa.coordinador.close(code=1000)
                except Exception:
                    pass
        sala.cerrar_sesion(db, actor_id=usuario["id"], sesion_id=sid)
        return {"ok": True, "codigo": codigo}
    finally:
        db.close()

# ── API: Validar código ────────────────────────────────────────
@app.get("/api/validar-codigo/{codigo}")
async def validar_codigo(codigo: str, usuario: dict = Depends(requiere_rol("estudiante"))):
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
        coord = db.query(models.Usuario).filter_by(id=sesion.coordinador_id).first()
        return {
            "valido": True,
            "sesion_id": sesion.id,
            "coordinador_nombre": _nombre_usuario(coord),
        }
    finally:
        db.close()

# ── API: Historial ─────────────────────────────────────────────
def _historial_sesion(db: Session, s: models.Sesion) -> dict | None:
    transcripciones = (
        db.query(models.Transcripcion)
        .filter_by(sesion_id=s.id)
        .order_by(models.Transcripcion.creado_en)
        .all()
    )
    if not transcripciones:
        return None
    usuarios = _mapa_usuarios(db)
    return {
        "id": s.id,
        "codigo": s.codigo,
        "iniciada_en": s.iniciada_en.strftime("%d/%m/%Y %H:%M") if s.iniciada_en else "",
        "finalizada_en": s.finalizada_en.strftime("%H:%M") if s.finalizada_en else "En curso",
        "mensajes": [
            {
                "tipo": t.tipo,
                "contenido": t.contenido,
                "hora": t.creado_en.strftime("%H:%M") if t.creado_en else "",
                "usuario": _nombre_usuario(usuarios.get(t.usuario_id)),
            }
            for t in transcripciones
        ],
    }

def _puede_ver_sesion(db: Session, sesion: models.Sesion, usuario: dict) -> bool:
    rol = usuario.get("rol")
    uid = usuario["id"]
    if rol == "admin":
        return True
    if rol == "coordinador":
        return sesion.coordinador_id == uid
    if rol == "estudiante":
        if db.query(models.SesionParticipante).filter_by(
            sesion_id=sesion.id, usuario_id=uid
        ).first():
            return True
        if sesion.estudiante_id == uid:
            return True
        return db.query(models.Transcripcion).filter_by(
            sesion_id=sesion.id, usuario_id=uid
        ).first() is not None
    return False

@app.get("/api/historial")
async def get_historial(
    sesion_id: Optional[int] = Query(None),
    usuario: dict = Depends(requiere_auth),
):
    db: Session = SessionLocal()
    try:
        if sesion_id:
            sesion = db.query(models.Sesion).filter_by(id=sesion_id).first()
            if not sesion:
                return JSONResponse(status_code=404, content={"error": "Sesión no encontrada."})
            if not _puede_ver_sesion(db, sesion, usuario):
                return JSONResponse(status_code=403, content={"error": "No tienes acceso a esta sala."})
            data = _historial_sesion(db, sesion)
            return [data] if data else []

        if usuario.get("rol") in ("coordinador", "estudiante"):
            return []

        sesiones = db.query(models.Sesion).order_by(models.Sesion.iniciada_en.desc()).limit(20).all()
        resultado = []
        for s in sesiones:
            item = _historial_sesion(db, s)
            if item:
                resultado.append(item)
        return resultado
    finally:
        db.close()

# ── API: Voz (Whisper local / Google) ──────────────────────────
@app.get("/api/voz/estado")
async def voz_estado(usuario: dict = Depends(requiere_auth)):
    try:
        from app.voz.transcripcion import estado_voz
        return estado_voz()
    except Exception as exc:
        return {
            "servidor": {"disponible": False, "modo": "sin_servicio", "motores": [], "preferencia": "auto"},
            "navegador": {"disponible": True, "modo": "online", "requiere_red": True},
            "error": str(exc),
        }

@app.post("/api/transcribir")
async def transcribir_audio(
    audio: UploadFile = File(...),
    preferir: Optional[str] = Form(None),
    usuario: dict = Depends(requiere_auth),
):
    try:
        from app.voz.transcripcion import transcribir_wav
        contenido = await audio.read()
        resultado = transcribir_wav(contenido, preferir=preferir)
        return resultado
    except ModuleNotFoundError:
        return JSONResponse(
            status_code=503,
            content={
                "error": "Falta instalar dependencias de voz (SpeechRecognition o faster-whisper).",
                "texto": "",
                "motor": None,
                "modo": "sin_servicio",
            },
        )
    except RuntimeError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": str(exc), "texto": "", "motor": None, "modo": "sin_servicio"},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "texto": "", "motor": None, "modo": "sin_servicio"},
        )

# ── WebSocket Coordinador ──────────────────────────────────────
@app.websocket("/ws/coordinador")
async def ws_coordinador(
    websocket: WebSocket,
    token: str = Query(...),
    sesion_id: int = Query(...),
):
    usuario = usuario_desde_token(token)
    if not usuario or usuario.get("rol") != "coordinador":
        await websocket.close(code=4003)
        return

    coordinador_id = usuario["id"]
    coordinador_nombre = usuario["nombre"]
    db: Session = SessionLocal()
    sesion = db.query(models.Sesion).filter_by(
        id=sesion_id,
        coordinador_id=coordinador_id,
        finalizada_en=None,
    ).first()

    if not sesion:
        await websocket.accept()
        await websocket.send_text(json.dumps({
            "tipo": "error",
            "contenido": "Sala no encontrada o ya finalizada.",
        }))
        await websocket.close(code=4002)
        db.close()
        return

    sala_activa = sala.ensure_memoria(sesion)
    await websocket.accept()
    sala.vincular_coordinador(sesion_id, websocket)

    await websocket.send_text(json.dumps({
        "tipo": "codigo_sala",
        "contenido": sesion.codigo,
        "estudiantes_conectados": len(sala_activa.estudiantes),
        "estudiantes": _participantes_estudiantes(db, sesion_id),
        "estudiantes_nombres": _nombres_participantes(db, sesion_id),
    }))

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("tipo") == "ping":
                continue
            msg = _enriquecer_msg_ws(msg, coordinador_nombre, coordinador_id, "coordinador")
            sala.guardar_transcripcion(
                db, sesion_id, msg["contenido"], msg["tipo"], coordinador_id
            )
            for est_ws in list(sala_activa.estudiantes.keys()):
                await est_ws.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        sala.desvincular_coordinador(websocket)
        db.close()

# ── WebSocket Estudiante ───────────────────────────────────────
@app.websocket("/ws/estudiante/{codigo}")
async def ws_estudiante(websocket: WebSocket, codigo: str, token: str = Query(...)):
    usuario = usuario_desde_token(token)
    if not usuario or usuario.get("rol") != "estudiante":
        await websocket.close(code=4003)
        return

    estudiante_id = usuario["id"]
    estudiante_nombre = usuario["nombre"]
    db: Session = SessionLocal()
    sesion = db.query(models.Sesion).filter_by(
        codigo=codigo.upper(),
        finalizada_en=None
    ).first()

    if not sesion:
        await websocket.close(code=4001)
        db.close()
        return

    if not sesion.estudiante_id and _es_estudiante_en_sesion(db, sesion, estudiante_id):
        sesion.estudiante_id = estudiante_id
    _registrar_participante(db, sesion.id, estudiante_id)
    registrar_auditoria(
        db, "estudiante_unido",
        f"Estudiante unido a sala {codigo.upper()}",
        actor_id=estudiante_id, sesion_id=sesion.id,
    )
    db.commit()

    sala_activa = sala.ensure_memoria(sesion)
    await websocket.accept()
    sala.vincular_estudiante(sesion.id, websocket, estudiante_id, estudiante_nombre)
    conectados = len(sala_activa.estudiantes)

    if sala_activa.coordinador:
        await sala_activa.coordinador.send_text(json.dumps({
            "tipo": "estudiante_conectado",
            "contenido": "",
            "nombre": estudiante_nombre,
            "estudiante_id": estudiante_id,
            "conectados": conectados,
        }))

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("tipo") == "ping":
                continue
            msg = _enriquecer_msg_ws(msg, estudiante_nombre, estudiante_id, "estudiante")
            sala.guardar_transcripcion(
                db, sesion.id, msg["contenido"], msg["tipo"], estudiante_id
            )
            if sala_activa.coordinador:
                await sala_activa.coordinador.send_text(json.dumps(msg))
            for est_ws in list(sala_activa.estudiantes.keys()):
                if est_ws is not websocket:
                    await est_ws.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        sid, info = sala.desvincular_estudiante(websocket)
        if sid and info and sala_activa.coordinador:
            try:
                await sala_activa.coordinador.send_text(json.dumps({
                    "tipo": "estudiante_desconectado",
                    "nombre": info.get("nombre"),
                    "estudiante_id": info.get("id"),
                    "conectados": len(sala_activa.estudiantes),
                }))
            except Exception:
                pass
        db.close()
