from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .manager import manager

router = APIRouter()


@router.websocket("/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            # 等待客戶端訊息或保持連線
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(client_id)
