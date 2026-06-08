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