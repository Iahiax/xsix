from mcp.server import Server
from mcp.types import Tool, TextContent
import json
from engines import data_engine, risk_engine, execution_engine, ml_engine, vps_controller

app = Server("uti-mcp-server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="get_market_data", description="جلب بيانات السوق الحية أو التاريخية لرمز معين من Capital.com", inputSchema={"type": "object", "properties": {"symbol": {"type": "string"}}}),
        Tool(name="execute_trade", description="تنفيذ صفقة شراء أو بيع مع حساب الرافعة الديناميكية وفحص المخاطر", inputSchema={"type": "object", "properties": {"symbol": {"type": "string"}, "side": {"type": "string", "enum": ["BUY", "SELL"]}, "size": {"type": "number"}}}),
        Tool(name="trigger_retraining", description="بدء دورة إعادة التدريب الذاتي (Retraining Pipeline) واختبار الظل (Shadow Testing)", inputSchema={"type": "object", "properties": {}}),
        Tool(name="vps_execute", description="تنفيذ أمر على خادم VPS عبر SSH مع بروتوكول الانتظار 63 ثانية", inputSchema={"type": "object", "properties": {"command": {"type": "string"}}}),
        Tool(name="check_risk_status", description="فحص حالة قاطع الدائرة اليومي (Circuit Breaker) والحد الأقصى للتراجع (Max Drawdown)", inputSchema={"type": "object", "properties": {}})
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "get_market_data":
            data = data_engine.fetch_symbol_data(arguments["symbol"])
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        elif name == "execute_trade":
            result = execution_engine.place_order(arguments["symbol"], arguments["side"], arguments["size"])
            return [TextContent(type="text", text=f"نتيجة التنفيذ: {json.dumps(result)}")]
        elif name == "trigger_retraining":
            result = ml_engine.run_retraining_pipeline()
            return [TextContent(type="text", text=result)]
        elif name == "vps_execute":
            result = vps_controller.execute_ssh_command(arguments["command"])
            return [TextContent(type="text", text=result)]
        elif name == "check_risk_status":
            status = risk_engine.get_global_risk_status()
            return [TextContent(type="text", text=json.dumps(status, indent=2))]
        else:
            return [TextContent(type="text", text=f"أداة غير معروفة: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"خطأ في تنفيذ الأداة: {str(e)}")]

