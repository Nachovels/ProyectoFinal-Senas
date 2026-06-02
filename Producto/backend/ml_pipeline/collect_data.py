import cv2
import mediapipe as mp
import numpy as np
import os

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
    mp_drawing.draw_landmarks(image, results.face_landmarks, mp_holistic.FACEMESH_CONTOURS, 
                             mp_drawing.DrawingSpec(color=(80,110,10), thickness=1, circle_radius=1)) 
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

DATA_PATH = os.path.join('dataset_sequences')
no_sequences = 30 
sequence_length = 30 

def get_next_sequence_number(letter_path):
    if not os.path.exists(letter_path): return 0
    existing_dirs = [d for d in os.listdir(letter_path) if os.path.isdir(os.path.join(letter_path, d))]
    nums = [int(d) for d in existing_dirs if d.isdigit()]
    return max(nums) + 1 if nums else 0

def collect_data():
    while True:
        raw_input = input("Gesto a recolectar (Gesto o 'salir' para terminar): ").strip().upper()
        if raw_input == 'SALIR': break
        
        letter = raw_input.replace(" ", "_").replace("¿", "").replace("?", "").replace("¡", "").replace("!", "")
        letter = letter.replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
        
        letter_path = os.path.join(DATA_PATH, letter)
        os.makedirs(letter_path, exist_ok=True)
        start_sequence = get_next_sequence_number(letter_path)
        cap = cv2.VideoCapture(0)
        with mp_holistic.Holistic(min_detection_confidence=0.5, min_tracking_confidence=0.5) as holistic:
            for sequence in range(start_sequence, start_sequence + no_sequences):
                while True:
                    ret, frame = cap.read()
                    image, results = mediapipe_detection(frame, holistic)
                    draw_styled_landmarks(image, results)
                    cv2.putText(image, f'LETRA: {letter} | VIDEO: {sequence}', (15,30), 2, 0.7, (0,255,0), 2)
                    cv2.putText(image, '"S" para grabar (1 seg)', (15,60), 2, 0.6, (255,255,255), 1)
                    cv2.imshow('Recolector data', image)
                    key = cv2.waitKey(10)
                    if key & 0xFF == ord('s'): break
                    if key & 0xFF == ord('q'): 
                        cap.release(); cv2.destroyAllWindows(); return
                for frame_num in range(sequence_length):
                    ret, frame = cap.read()
                    image, results = mediapipe_detection(frame, holistic)
                    draw_styled_landmarks(image, results)
                    cv2.putText(image, f'GRABANDO {letter} - {frame_num}/30', (15,30), 2, 1, (0,0,255), 2)
                    cv2.imshow('Recolector data', image)
                    keypoints = extract_keypoints(results)
                    seq_path = os.path.join(letter_path, str(sequence))
                    os.makedirs(seq_path, exist_ok=True)
                    np.save(os.path.join(seq_path, str(frame_num)), keypoints)
                    cv2.waitKey(10)
            cap.release(); cv2.destroyAllWindows()

if __name__ == '__main__':
    collect_data()
