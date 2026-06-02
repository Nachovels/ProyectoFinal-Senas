import os
import numpy as np
from sklearn.model_selection import train_test_split
from tensorflow.keras.utils import to_categorical
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping

DATA_PATH = os.path.join('dataset_sequences')
letters = np.array(sorted([f for f in os.listdir(DATA_PATH) if os.path.isdir(os.path.join(DATA_PATH, f))]))
label_map = {label:num for num, label in enumerate(letters)}

def normalize_features(frame_data):
    new_data = frame_data.copy()
    
    # 1. Pose (0-131)
    if np.any(new_data[0:132]):
        nose_x, nose_y, nose_z = new_data[0], new_data[1], new_data[2]
        # Centrar
        for i in range(0, 132, 4):
            new_data[i] -= nose_x
            new_data[i+1] -= nose_y
            new_data[i+2] -= nose_z
        # Escalar
        max_val = np.max(np.abs(new_data[0:132]))
        if max_val > 0:
            new_data[0:132] = new_data[0:132] / max_val
            
    # 2. Face (132-275)
    if np.any(new_data[132:276]):
        ref_x, ref_y, ref_z = new_data[132], new_data[133], new_data[134]
        # Centrar
        for i in range(132, 276, 3):
            new_data[i] -= ref_x
            new_data[i+1] -= ref_y
            new_data[i+2] -= ref_z
        # Escalar
        max_val = np.max(np.abs(new_data[132:276]))
        if max_val > 0:
            new_data[132:276] = new_data[132:276] / max_val
            
    # 3. Mano Izquierda (276-338)
    if np.any(new_data[276:339]):
        wrist_x, wrist_y, wrist_z = new_data[276], new_data[277], new_data[278]
        # Centrar
        for i in range(276, 339, 3):
            new_data[i] -= wrist_x
            new_data[i+1] -= wrist_y
            new_data[i+2] -= wrist_z
        # Escalar
        max_val = np.max(np.abs(new_data[276:339]))
        if max_val > 0:
            new_data[276:339] = new_data[276:339] / max_val
            
    # 4. Mano Derecha (339-401)
    if np.any(new_data[339:402]):
        wrist_x, wrist_y, wrist_z = new_data[339], new_data[340], new_data[341]
        # Centrar
        for i in range(339, 402, 3):
            new_data[i] -= wrist_x
            new_data[i+1] -= wrist_y
            new_data[i+2] -= wrist_z
        # Escalar
        max_val = np.max(np.abs(new_data[339:402]))
        if max_val > 0:
            new_data[339:402] = new_data[339:402] / max_val
            
    return new_data

def load_data():
    sequences, labels = [], []
    for letter in letters:
        letter_path = os.path.join(DATA_PATH, letter)
        for seq_dir in os.listdir(letter_path):
            window = []
            seq_full_path = os.path.join(letter_path, seq_dir)
            if not os.path.isdir(seq_full_path): continue
            for frame_num in range(30):
                res = np.load(os.path.join(seq_full_path, f"{frame_num}.npy"))
                res = normalize_features(res) # Aplicar normalización al cargar
                window.append(res)
            sequences.append(window)
            labels.append(label_map[letter])
    
    return np.array(sequences, dtype=np.float32), np.array(labels)

def train():
    print("Cargando datos...")
    X, y = load_data()
    if len(X) == 0: return
    y = to_categorical(y).astype(int)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.1, stratify=y)
    
    print("Entrenando Modelo Optimizado...")
    model = Sequential()

    model.add(LSTM(64, return_sequences=True, activation='tanh', input_shape=(30,402)))
    model.add(BatchNormalization())
    model.add(Dropout(0.2))
    
    model.add(LSTM(128, return_sequences=True, activation='tanh'))
    model.add(BatchNormalization())
    model.add(Dropout(0.2))
    
    model.add(LSTM(64, return_sequences=False, activation='tanh'))
    model.add(BatchNormalization())
    
    model.add(Dense(64, activation='relu'))
    model.add(Dense(32, activation='relu'))
    model.add(Dense(letters.shape[0], activation='softmax'))
    
    optimizer = Adam(learning_rate=0.0001)
    model.compile(optimizer=optimizer, loss='categorical_crossentropy', metrics=['categorical_accuracy'])
    
    early_stopping = EarlyStopping(monitor='val_loss', patience=50, restore_best_weights=True)
    
    model.fit(X_train, y_train, epochs=500, batch_size=8, validation_data=(X_test, y_test), callbacks=[early_stopping])
    
    model.save('alphabet_lstm_model.h5')
    print("Modelo guardado exitosamente.")

if __name__ == '__main__':
    train()
