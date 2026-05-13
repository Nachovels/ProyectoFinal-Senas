import os
import numpy as np

OLD_PATH = 'dataset_static'
NEW_PATH = 'dataset_sequences'
SEQ_LEN = 30 

def migrate():
    if not os.path.exists(OLD_PATH): return
    letters = [f for f in os.listdir(OLD_PATH) if os.path.isdir(os.path.join(OLD_PATH, f))]
    
    for letter in letters:
        print(f"Migrando {letter}...")
        old_letter_path = os.path.join(OLD_PATH, letter)
        new_letter_path = os.path.join(NEW_PATH, letter)
        os.makedirs(new_letter_path, exist_ok=True)
        files = sorted([f for f in os.listdir(old_letter_path) if f.endswith('.npy')], key=lambda x: int(x.split('.')[0]))
        
        for i in range(0, len(files) - SEQ_LEN + 1, SEQ_LEN):
            sequence_num = i // SEQ_LEN
            seq_path = os.path.join(new_letter_path, str(sequence_num))
            os.makedirs(seq_path, exist_ok=True)
            for frame_num in range(SEQ_LEN):
                old_data = np.load(os.path.join(old_letter_path, files[i + frame_num]))
                
                new_data = np.zeros(402)
                
                new_data[339:402] = old_data
                new_data[276:339] = old_data
                
                np.save(os.path.join(seq_path, str(frame_num)), new_data)
    print("Migración V2.1 finalizada.")

if __name__ == '__main__':
    migrate()
