from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json
import asyncio

app = FastAPI(title="UTI Chat UI Backend")

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

manager = ConnectionManager()

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # استقبال رسالة من واجهة المستخدم
            data = await websocket.receive_text()
            user_input = json.loads(data)
            
            # هنا يتم إرسال الطلب إلى نموذج LLM (عبر OpenRouter أو Local LLM)
            # مع تزويده بأدوات MCP للاستدعاء
            response = await process_with_llm_and_mcp(user_input["message"])
            
            # إرسال الرد مع حالة النظام
            await websocket.send_text(json.dumps({
                "role": "assistant",
                "content": response["text"],
                "system_status": get_system_status(),
                "generated_code": response.get("code", None)
            }))
    except WebSocketDisconnect:
        manager.active_connections.remove(websocket)

def get_system_status():
    return {
        "mode": "DEMO",
        "active_symbols": 150,
        "daily_pnl": "+1.2%",
        "drawdown": "0.5%",
        "training_status": "Idle"
    }

async def process_with_llm_and_mcp(message: str):
    # محاكاة لاستجابة النموذج بعد استخدام أدوات MCP
    return {
        "text": f"تم استلام طلبك: '{message}'. قمت باستدعاء محرك المخاطر والتأكد من أن جميع الشروط آمنة. جاري التنفيذ...",
        "code": "print('Execution logic triggered')"
    }

