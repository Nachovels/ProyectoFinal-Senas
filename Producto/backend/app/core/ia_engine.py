import os
import cv2
import numpy as np
import mediapipe as mp
import base64
import time
from tensorflow.keras.models import load_model
import google.generativeai as genai
import dotenv

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
dotenv.load_dotenv(dotenv_path=env_path)

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if API_KEY:
    genai.configure(api_key=API_KEY)
    model_gemini = genai.GenerativeModel('gemini-flash-latest')
else:
    print("ADVERTENCIA: No se encontró la API KEY de Gemini en el archivo .env")
    model_gemini = None

mp_holistic = mp.solutions.holistic

class SignTranslator:
    def __init__(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.model_path = os.path.join(base_dir, 'ml_pipeline', 'alphabet_lstm_model.h5')
        self.dataset_path = os.path.join(base_dir, 'ml_pipeline', 'dataset_sequences')
        
        if os.path.exists(self.dataset_path):
            self.letters = np.array(sorted([f for f in os.listdir(self.dataset_path) if os.path.isdir(os.path.join(self.dataset_path, f))]))
        else:
            self.letters = np.array([])
            
        self.lstm_model = load_model(self.model_path)
        self.sequence = []
        self.threshold = 0.90
        
        self.glosas = []
        self.last_sign_time = time.time()
        
        self.consecutive_predictions = 0
        self.last_predicted_word = None
        self.stability_threshold = 5  
        
        self.holistic = mp_holistic.Holistic(min_detection_confidence=0.5, min_tracking_confidence=0.5)
        
        try:
            dummy_sequence = np.zeros((1, 30, 402))
            self.lstm_model(dummy_sequence, training=False)
            print("Modelo inicializado.")
        except Exception as e:
            print("Advertencia en el warm-up del modelo:", e)

    def process_base64_frame(self, base64_string):
        """Procesa un frame en base64 y retorna (prediccion_actual, oracion_completa)"""
        try:
            img_data = base64.b64decode(base64_string)
            np_arr = np.frombuffer(img_data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        except Exception as e:
            print("Error decodificando imagen:", e)
            return None, None

        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image.flags.writeable = False
        results = self.holistic.process(image)

        keypoints = self.extract_keypoints(results)
        keypoints = self.normalize_features(keypoints)

        prediccion_actual = None
        oracion_completa = None

        if np.any(keypoints[-126:] != 0):
            self.last_sign_time = time.time()
            self.sequence.append(keypoints)
            self.sequence = self.sequence[-30:]
            
            if len(self.sequence) == 30:
                res = self.lstm_model(np.expand_dims(self.sequence, axis=0), training=False)[0].numpy()
                prediction_idx = np.argmax(res)
                confidence = res[prediction_idx]
                
                if confidence > self.threshold and len(self.letters) > prediction_idx:
                    letra = self.letters[prediction_idx]
                    prediccion_actual = letra
                    
                    if self.last_predicted_word == letra:
                        self.consecutive_predictions += 1
                    else:
                        self.last_predicted_word = letra
                        self.consecutive_predictions = 1
                        
                    if self.consecutive_predictions == self.stability_threshold:
                        if not self.glosas or self.glosas[-1] != letra:
                            self.glosas.append(letra)
                            print(f"[IA Engine] Nueva seña guardada: {letra} | Buffer actual: {self.glosas}")
                else:
                    self.consecutive_predictions = 0
        else:
            self.sequence = []
            self.last_predicted_word = None
            self.consecutive_predictions = 0
            
            if len(self.glosas) > 0 and (time.time() - self.last_sign_time) > 2.5:
                glosas_a_traducir = self.glosas.copy()
                self.glosas = [] # Limpiar buffer para la siguiente oración
                return prediccion_actual, glosas_a_traducir

        return prediccion_actual, None

    def traducir_con_gemini(self, glosas):
        secuencia = " ".join(glosas)
        prompt = f"""
        Eres el motor de traducción de 'SpeakingHands', una plataforma para estudiantes sordos en una universidad de Chile.
        El sistema de visión artificial detectó la siguiente secuencia de señas (glosas): {secuencia}.
        
        Tu tarea:
        1. Interpretar las glosas y construir una oración coherente, fluida y gramaticalmente correcta en español.
        2. IMPORTANTE (Filtro de Ruido): Las señas provienen de un sensor visual propenso a captar "basura" durante las transiciones de las manos. Si notas palabras que no tienen sentido lógico interrumpiendo un deletreo (ej: "J O ENTIENDO NO S E"), ignora las palabras ruido ("ENTIENDO", "NO") y deduce la palabra correcta ("José").
        3. Las letras sueltas consecutivas representan el deletreo manual de un nombre o palabra. Debes unirlas.
        4. El contexto es una conversación formal entre un estudiante sordo y un coordinador de carrera. Adapta el sentido de la frase a temas universitarios (certificados, matrícula, horario, prueba, etc.).
        5. Responder EXCLUSIVAMENTE con la oración final. Sin explicaciones, saludos iniciales, ni comillas.
        """
        try:
            response = model_gemini.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print("Error en Gemini:", e)
            return "Has superado el límite de uso gratuito de la IA (Gemini). Por favor, espera unos 30 segundos antes de enviar más señas."

    def extract_keypoints(self, results):
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

    def normalize_features(self, frame_data):
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
