"""程式入口。

Java 對照：相當於 @SpringBootApplication 加 @RestController。
啟動方式：uvicorn app.main:app --reload
（app.main 是模組路徑，:app 是模組內名為 app 的物件，相當於 Spring 的 main 類別）
"""
import logging
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import GroupSource, JoinEvent, MessageEvent, TextMessageContent

from app import line_client
from app.config import load_settings
from app.db import Database
from app.handlers import BOUND_GROUP_KEY, Context, check_group, handle_command
from app.models import TZ

# 預設 Python 只顯示 WARNING 以上，要設定才看得到我們自己的 INFO log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("line-bot-5v5")

settings = load_settings()
parser = WebhookParser(settings.channel_secret)  # 負責驗證簽章並解析事件
db = Database(settings.db_path)
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
        try:
            await process_event(event)
        except Exception:
            # 單一事件失敗不影響對 LINE 回 200（否則 LINE 會重送），但要留下完整錯誤
            logger.exception("failed to process event")

    return {"status": "ok"}


async def process_event(event) -> None:
    # 只處理群組事件，一對一聊天與多人聊天室一律忽略
    if not isinstance(event.source, GroupSource):
        return
    group_id = event.source.group_id
    bound = db.get_setting(BOUND_GROUP_KEY)

    if isinstance(event, JoinEvent):
        # Bot 被拉進群組：已綁定其他群組時，直接退出
        if bound is not None and group_id != bound:
            logger.warning("left unauthorized group %s", group_id)
            await line_client.leave_group(group_id)
        return

    if not (isinstance(event, MessageEvent) and isinstance(event.message, TextMessageContent)):
        return
    text = event.message.text

    action = check_group(bound, group_id, text)
    if action == "leave":
        logger.warning("left unauthorized group %s", group_id)
        await line_client.leave_group(group_id)
        return
    if action == "ignore":
        return

    user_id = event.source.user_id
    if user_id is None:
        return

    # 每次查最新的顯示名稱；查詢失敗時退回已記錄的名稱
    known = db.get_member_by_user_id(user_id)
    try:
        name = await line_client.get_display_name(group_id, user_id)
    except Exception:
        logger.exception("failed to fetch display name")
        name = known.display_name if known else "未知成員"

    ctx = Context(db=db, group_id=group_id, user_id=user_id, display_name=name, now=datetime.now(TZ))
    reply = handle_command(ctx, text)
    logger.info("text=%r reply=%r", text, reply)
    if reply is not None:
        await line_client.reply_text(event.reply_token, reply)
