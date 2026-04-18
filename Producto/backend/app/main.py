from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import json

app = FastAPI(title="AccesClass")

# Lista de conexiones activas
conexiones: list[WebSocket] = []

@app.get("/")
async def index():
    with open("../frontend/templates/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/estudiante")
async def estudiante():
    with open("../frontend/templates/estudiante.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    conexiones.append(websocket)
    try:
        while True:
            # Recibe el texto del coordinador
            data = await websocket.receive_text()
            # Lo reenvía a TODOS los conectados
            for conexion in conexiones:
                if conexion != websocket:
                    await conexion.send_text(data)
    except WebSocketDisconnect:
        conexiones.remove(websocket)