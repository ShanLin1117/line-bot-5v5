"""程式入口。

Java 對照：相當於 @SpringBootApplication 加 @RestController。
啟動方式：uvicorn app.main:app --reload
（app.main 是模組路徑，:app 是模組內名為 app 的物件，相當於 Spring 的 main 類別）
"""
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.config import load_settings
from app.handlers import handle_text

logger = logging.getLogger("line-bot-5v5")

settings = load_settings()
parser = WebhookParser(settings.channel_secret)  # 負責驗證簽章並解析事件
app = FastAPI(title="line-bot-5v5")


# 裝飾器 @app.get 相當於 Spring 的 @GetMapping("/health")
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# async def 是非同步函式，FastAPI 在這裡需要它來讀取原始 request body。
# 參數 x_line_signature 會自動對應到 HTTP header「X-Line-Signature」，
# 相當於 Spring 的 @RequestHeader。
@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(default="")):
    # 簽章驗證必須用「原始 body」，所以不能先交給框架解析成 JSON
    body = (await request.body()).decode("utf-8")

    try:
        events = parser.parse(body, x_line_signature)
    except InvalidSignatureError:
        # 簽章不符，代表請求不是 LINE 送的，回 400
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if isinstance(event, MessageEvent) and isinstance(
            event.message, TextMessageContent
        ):
            reply = handle_text(event.message.text)
            # 目前只記 log；下一步會用 Messaging API 真正回覆
            logger.info("text=%r reply=%r", event.message.text, reply)

    return {"status": "ok"}
