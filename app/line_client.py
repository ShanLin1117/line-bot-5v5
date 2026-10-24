"""LINE Messaging API 呼叫的薄封裝。

把 SDK 集中在這裡，main.py 與測試都只面對簡單的函式，測試時可以整個替換掉。
"""
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    TextMessage,
)

from app.config import load_settings

_config = Configuration(access_token=load_settings().channel_access_token)


async def reply_text(reply_token: str, text: str) -> None:
    """回覆文字。

    reply_token 是 LINE 隨每個事件附上的一次性憑證，只能用一次、
    且有效時間很短，所以必須在收到事件後立刻回覆。回覆不計入每月推播額度。
    `async with` 類似 Java 的 try-with-resources：離開區塊時自動關閉連線。
    """
    async with AsyncApiClient(_config) as api_client:
        await AsyncMessagingApi(api_client).reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=text)])
        )


async def get_display_name(group_id: str, user_id: str) -> str:
    """查詢群組成員的 LINE 顯示名稱。"""
    async with AsyncApiClient(_config) as api_client:
        profile = await AsyncMessagingApi(api_client).get_group_member_profile(group_id, user_id)
        return profile.display_name


async def leave_group(group_id: str) -> None:
    async with AsyncApiClient(_config) as api_client:
        await AsyncMessagingApi(api_client).leave_group(group_id)
