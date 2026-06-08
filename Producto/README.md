# SpeakingHands — Producto

Aplicación web de comunicación accesible entre **coordinador** y **estudiantes**: chat en tiempo real, frases rápidas y transcripción de voz (Google en navegador/servidor + Whisper como respaldo).

## Estructura

```
Producto/
├── backend/          # API FastAPI + WebSockets + voz
│   ├── app/
│   │   ├── main.py           # Rutas, salas, admin, WS
│   │   ├── core/             # Auth JWT, conexión MySQL
│   │   ├── models/           # SQLAlchemy (incl. participantes_sesion)
│   │   └── voz/              # Google Speech + faster-whisper
│   ├── ml_pipeline/          # IA señas (opcional)
│   ├── schema.sql            # Esquema MySQL
│   └── requirements.txt
└── frontend/
    ├── templates/            # HTML (admin, coordinador, estudiante)
    └── js/                   # voz-sesion.js (compartido)
```

## Requisitos

| Componente | Versión |
|------------|---------|
| Python | 3.11+ |
| MySQL | 8.x |
| Navegador | Chrome/Edge (voz en navegador) |

## Instalación

```bash
cd Producto/backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # editar DB y SECRET_KEY
```

Importar la base de datos:

```bash
mysql -u root -p < schema.sql
```

Precargar modelo Whisper (primera vez, requiere internet):

```bash
python -m app.voz.transcripcion
```

Arrancar servidor:

```bash
python -m uvicorn app.main:app --reload
```

Abrir `http://127.0.0.1:8000` — usuarios demo en `schema.sql` (contraseña: `demo`).

## Funcionalidades implementadas

- **Auth JWT** con roles admin, coordinador y estudiante
- **Varias salas simultáneas** por coordinador
- **Varios estudiantes por sesión** (`participantes_sesion`)
- **WebSockets** por `sesion_id` con nombres reales en el chat
- **Mensajes entre estudiantes** de la misma sala
- **Voz**: reconocimiento en navegador + transcripción WAV en servidor
- **Panel admin**: usuarios, salas (multi-estudiante), frases, auditoría
- **Layouts unificados** coordinador / estudiante (480px, chat + composición)

## Pipeline ML (opcional)

```bash
pip install -r requirements-ml.txt
cd ml_pipeline
python collect_data.py
python train_model.py
```

## Variables de entorno

Ver `backend/.env.example` — base de datos, JWT, motores de voz y simulación de fallos para pruebas.
