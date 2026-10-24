"""讀取設定。

Java 對照：相當於 application.yml + @ConfigurationProperties。
Python 慣例是把機密放在環境變數，本機開發則放在 .env，由 python-dotenv 載入。
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

# 讀取專案根目錄的 .env，寫入 os.environ（已存在的環境變數不會被覆蓋）
load_dotenv()


# dataclass 約等於 Java 的 record：自動產生建構子、equals、toString
# frozen=True 表示建立後不可修改（類似 final 欄位）
@dataclass(frozen=True)
class Settings:
    channel_secret: str
    channel_access_token: str


def load_settings() -> Settings:
    return Settings(
        channel_secret=os.getenv("LINE_CHANNEL_SECRET", ""),
        channel_access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
    )
