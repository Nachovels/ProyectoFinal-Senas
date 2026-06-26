# SpeakingHands 🤝

Plataforma web de comunicación bidireccional e inclusiva para entornos educacionales.

**Proyecto de Titulación — Analista Programadora Computacional**  
Duoc UC, Sede Viña del Mar · 2026  
Cliente: Universidad de las Américas (UDLA)

---

## ¿Qué es SpeakingHands?

SpeakingHands es una plataforma web que permite la comunicación en tiempo real entre personas con discapacidad auditiva o de habla y personas oyentes dentro de entornos educacionales. El sistema facilita la interacción entre un coordinador (docente/funcionario) y uno o más estudiantes mediante:

- 🎙️ **Voz a texto en tiempo real** — el coordinador habla y el texto aparece en pantalla del estudiante automáticamente
- ✋ **Reconocimiento de lengua de señas con IA** — módulo basado en MediaPipe y modelo LSTM
- 💬 **Panel de frases rápidas** — comunicación de respaldo bidireccional con text-to-speech
- ✏️ **Escritura libre** — el estudiante puede escribir y enviar texto al coordinador
- 🔑 **Códigos de sala** — el coordinador genera un código único para que el estudiante se una
- 📋 **Historial de sesiones** — registro completo de la comunicación guardado en base de datos
- ♿ **Toolbar de accesibilidad** — tamaño de letra ajustable, alto contraste y notificación sonora
- 🛡️ **Panel de administración** — gestión de usuarios, salas, frases rápidas y auditoría

---

## Estructura del proyecto

```
ProyectoFinal-Senas/
└── Producto/
    ├── backend/
    │   ├── app/
    │   │   ├── core/
    │   │   │   ├── auth.py          # JWT, bcrypt, helpers de autenticación
    │   │   │   └── database.py      # Conexión MySQL con SQLAlchemy
    │   │   ├── models/
    │   │   │   └── models.py        # Modelos: Usuario, Sesion, Transcripcion, etc.
    │   │   └── main.py              # FastAPI: rutas, WebSockets, endpoints
    │   ├── ml_pipeline/             # Módulo IA
    │   ├── .env                     # Variables de entorno (no subir a Git)
    │   ├── requirements.txt         # Dependencias Python
    │   └── schema.sql               # Script SQL para crear la base de datos
    └── frontend/
        ├── js/
        │   └── accesibilidad.js     # Toolbar accesibilidad, toasts, notificaciones
        └── templates/
            ├── login.html           # Pantalla de inicio de sesión
            ├── coordinador.html     # Vista del coordinador
            ├── estudiante.html      # Vista del estudiante
            └── admin.html           # Panel de administración
```

---

## Requisitos previos

- Python 3.11+
- MySQL (XAMPP recomendado para desarrollo local)
- Google Chrome (necesario para el reconocimiento de voz)
- Git

---

## Instalación y ejecución

### 1. Clonar el repositorio

```bash
git clone https://github.com/Nachovels/ProyectoFinal-Senas
cd ProyectoFinal-Senas
```

### 2. Crear y activar el entorno virtual

```bash
cd Producto/backend

# Crear entorno virtual
python -m venv venv

# Activar en Windows (PowerShell)
venv\Scripts\activate

# Activar en Mac/Linux
source venv/bin/activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno

Crear el archivo `Producto/backend/.env` basándose en `.env.example`:

```env
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=speaking_hands
SECRET_KEY=speakinghands_secret_2026
```

### 5. Configurar la base de datos

1. Abrir XAMPP y activar Apache y MySQL
2. Ir a `http://localhost/phpmyadmin`
3. Crear la base de datos y las tablas ejecutando el script:

```sql
-- En phpMyAdmin, seleccionar "SQL" y pegar el contenido de schema.sql
source Producto/backend/schema.sql
```

### 6. Crear usuarios de prueba

Generar el hash de contraseña con el venv activado:

```bash
python -c "from passlib.context import CryptContext; ctx = CryptContext(schemes=['bcrypt']); print(ctx.hash('demo'))"
```

Insertar en phpMyAdmin con el hash generado:

```sql
USE speaking_hands;

INSERT INTO usuarios (nombre, email, password, rol_id) VALUES
('Admin Demo',        'admin@demo.cl',        'HASH_AQUI', 1),
('Coordinador Demo',  'coordinador@demo.cl',  'HASH_AQUI', 2),
('Estudiante Demo',   'estudiante@demo.cl',   'HASH_AQUI', 3);
```

### 7. Correr el servidor

```bash
cd Producto/backend
venv\Scripts\activate
uvicorn app.main:app --reload
```

El servidor estará disponible en: `http://localhost:8000`

---

## Flujo de uso

### 👨‍🏫 Coordinador

1. Ir a `http://localhost:8000/login`
2. Iniciar sesión con credenciales de coordinador
3. Hacer clic en **+ Crear reunión**
4. Compartir el código de 6 caracteres con el estudiante
5. Hacer clic en **Entrar a la sala**
6. Usar el micrófono para hablar — el texto aparece en pantalla del estudiante en tiempo real
7. También puede escribir texto o usar frases rápidas
8. Al terminar, hacer clic en **Terminar sesión**

### 🎓 Estudiante

1. Ir a `http://localhost:8000/login`
2. Iniciar sesión con credenciales de estudiante
3. Ingresar el código de sala compartido por el coordinador
4. Hacer clic en **Unirse →**
5. Los mensajes del coordinador aparecen automáticamente en el chat
6. Responder usando frases rápidas, escritura libre o señas (módulo IA)

### 🛡️ Administrador

1. Ir a `http://localhost:8000/login`
2. Iniciar sesión con credenciales de administrador
3. Gestionar usuarios, salas, frases rápidas y ver auditoría

---

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Backend | FastAPI, SQLAlchemy, PyMySQL |
| Base de datos | MySQL |
| Autenticación | JWT, bcrypt |
| IA / ML | MediaPipe, LSTM |
| Voz a texto | Web Speech API |
| Tiempo real | WebSockets |
| Frontend | HTML, CSS, JavaScript vanilla |
