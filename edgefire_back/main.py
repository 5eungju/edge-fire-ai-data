from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import time, json
import uuid, httpx, os
from fastapi import Depends
from storage_api import router as storage_router, authorized, db, AI_URL

app = FastAPI(title="EDGE-FIRE Backend API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3100", "http://localhost:3100"], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-API-Key"])
app.include_router(storage_router)

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
    environment: Optional[dict[str, float]] = None
    camera_azimuth: Optional[float] = Field(None, example=185.4)

@app.get("/")
def read_root():
    return {"status": "ONLINE", "message": "EDGE-FIRE 6~8주차 통합 백엔드 작동 중"}

@app.post("/api/v1/telemetry/multimodal", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(authorized)])
async def ingest_telemetry(payload: TelemetryRequest, background_tasks: BackgroundTasks):
    packet_data = payload.model_dump(exclude_none=True)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(AI_URL+'/api/v1/ai/assess',json=packet_data,headers={'X-API-Key':os.environ['LOCAL_API_TOKEN']})
        response.raise_for_status()
        assessment=response.json()
    except Exception:
        assessment={'status':'AI_UNAVAILABLE','risk_level':None,'operational_use':False}
    event_id='EVT_'+uuid.uuid4().hex
    with db() as con:
        con.execute('INSERT INTO telemetry VALUES(?,?,?,?)',(event_id,time.time(),json.dumps(packet_data),json.dumps(assessment)))
    background_tasks.add_task(manager.broadcast, packet_data | {'assessment':assessment,'event_id':event_id})
    return {'status':'STORED','node_id':payload.node_id,'event_id':event_id,'assessment':assessment}

@app.websocket("/api/v1/ws/hazard")
async def websocket_endpoint(websocket: WebSocket):
    if websocket.headers.get('origin') not in ['http://127.0.0.1:3100','http://localhost:3100']:
        await websocket.close(code=1008)
        return
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"PONG: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
