"""指令處理。

Java 對照：相當於 Service 層。刻意寫成「純函式」（輸入文字、輸出回覆文字），
不依賴 LINE SDK 與 FastAPI，所以可以直接單元測試。
"""


def handle_text(text: str) -> str | None:
    """依文字指令回傳要回覆的內容；不是指令則回傳 None（不回覆）。

    `str | None` 是型別提示，相當於 Java 的 Optional<String>，
    但 Python 不會在執行期強制檢查，主要給 IDE 與讀者看。
    """
    text = text.strip()
    if not text.startswith("/"):
        return None

    command = text.split()[0]
    if command == "/名單":
        return "目前尚無報名資料（功能開發中）"
    return None
