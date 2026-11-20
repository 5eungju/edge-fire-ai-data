from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import time, json

app = FastAPI(title="EDGE-FIRE Backend API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

class GasMetrics(BaseModel):
    CO: float = Field(..., example=45.2)
    H2: float = Field(..., example=12.1)
    VOC: float = Field(..., example=110.5)

class TelemetryRequest(BaseModel):
    node_id: str = Field(..., example="NODE_WUI_0102")
    sequence_no: int = Field(..., example=1042)
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    gas_data: GasMetrics
    camera_azimuth: Optional[float] = Field(None, example=185.4)

@app.get("/")
def read_root():
    return {"status": "ONLINE", "message": "EDGE-FIRE 6~8주차 통합 백엔드 작동 중"}

@app.post("/api/v1/telemetry/multimodal", status_code=status.HTTP_202_ACCEPTED)
async def ingest_telemetry(payload: TelemetryRequest, background_tasks: BackgroundTasks):
    packet_data = payload.dict()
    background_tasks.add_task(manager.broadcast, packet_data)
    return {"status": "QUEUED", "node_id": payload.node_id, "event_id": f"EVT_{payload.timestamp}"}

@app.websocket("/api/v1/ws/hazard")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"PONG: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
