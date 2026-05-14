import cv2
import numpy as np
import mediapipe as mp
import os
from tensorflow.keras.models import load_model

mp_holistic = mp.solutions.holistic
mp_drawing = mp.solutions.drawing_utils

def mediapipe_detection(image, model):
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image.flags.writeable = False
    results = model.process(image)
    image.flags.writeable = True
    image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    return image, results

def draw_styled_landmarks(image, results):
    mp_drawing.draw_landmarks(image, results.face_landmarks, mp_holistic.FACEMESH_CONTOURS) 
    mp_drawing.draw_landmarks(image, results.pose_landmarks, mp_holistic.POSE_CONNECTIONS) 
    mp_drawing.draw_landmarks(image, results.left_hand_landmarks, mp_holistic.HAND_CONNECTIONS) 
    mp_drawing.draw_landmarks(image, results.right_hand_landmarks, mp_holistic.HAND_CONNECTIONS) 

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
    if np.any(new_data[132:276]):
        ref_x, ref_y, ref_z = new_data[132], new_data[133], new_data[134]
        for i in range(132, 276, 3):
            new_data[i] -= ref_x
            new_data[i+1] -= ref_y
            new_data[i+2] -= ref_z
    if np.any(new_data[276:339]):
        wrist_x, wrist_y, wrist_z = new_data[276], new_data[277], new_data[278]
        for i in range(276, 339, 3):
            new_data[i] -= wrist_x
            new_data[i+1] -= wrist_y
            new_data[i+2] -= wrist_z
    if np.any(new_data[339:402]):
        wrist_x, wrist_y, wrist_z = new_data[339], new_data[340], new_data[341]
        for i in range(339, 402, 3):
            new_data[i] -= wrist_x
            new_data[i+1] -= wrist_y
            new_data[i+2] -= wrist_z
    return new_data

DATA_PATH = os.path.join('dataset_sequences')
letters = np.array(sorted([f for f in os.listdir(DATA_PATH) if os.path.isdir(os.path.join(DATA_PATH, f))]))
model = load_model('alphabet_lstm_model.h5')

def test_model():
    sequence = []
    threshold = 0.8 

    cap = cv2.VideoCapture(0)
    with mp_holistic.Holistic(min_detection_confidence=0.5, min_tracking_confidence=0.5) as holistic:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret: break
            
            image, results = mediapipe_detection(frame, holistic)
            draw_styled_landmarks(image, results)
            
            
            keypoints = extract_keypoints(results)
            keypoints = normalize_features(keypoints)

            
            if np.any(keypoints[-126:] != 0):
                sequence.append(keypoints)
                sequence = sequence[-30:] 
                if len(sequence) == 30:
                    res = model.predict(np.expand_dims(sequence, axis=0))[0]
                    prediction_idx = np.argmax(res)
                    confidence = res[prediction_idx]
                    
                    
                    if confidence > threshold:
                        predicted_letter = letters[prediction_idx]
                        
                        # Dibujar interfaz
                        cv2.rectangle(image, (0,0), (640, 45), (245, 117, 16), -1)
                        cv2.putText(image, f'LETRA DETECTADA: {predicted_letter}', (15,35), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
                        cv2.putText(image, f'{confidence*100:.1f} %', (500,35), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
            else:
                sequence = []
                cv2.putText(image, 'ESPERANDO MANO...', (15,35), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)

            cv2.imshow('Traductor V2.1 Prof.', image)
            if cv2.waitKey(10) & 0xFF == ord('q'): break
        cap.release(); cv2.destroyAllWindows()

if __name__ == '__main__':
    test_model()
