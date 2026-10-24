# line-bot-5v5

LINE 群組球賽分組機器人：自動推播每週報名卡、截止報名，並依身高、體重與位置隨機分組，讓各隊戰力均衡。

## 功能（規劃中）

- [x] 專案骨架：FastAPI + LINE Webhook 簽章驗證
- [ ] 回覆訊息（Messaging API）
- [ ] 球員資料設定（`/設定`）
- [ ] 每週報名卡（Flex Message）
- [ ] 排程：週日 20:00 推播、週二 24:00 截止
- [ ] 分組演算法與 `/分組` 預覽
- [ ] 帶人、暫停本週等管理指令

## 技術棧

- Python 3.13
- FastAPI + Uvicorn
- line-bot-sdk（v3）
- pytest

## 專案結構

```
app/
├── main.py       # 程式入口，/health 與 /callback
├── config.py     # 讀取 .env 設定
└── handlers.py   # 指令處理（純函式，易於測試）
tests/            # 測試
tmp/              # 暫存檔（不進版控）
```

## 快速開始

以下為 PowerShell 指令。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # 再填入 LINE 頻道的金鑰
```

啟動開發伺服器：

```powershell
uvicorn app.main:app --reload
```

- 健康檢查：<http://127.0.0.1:8000/health>
- 自動產生的 API 文件：<http://127.0.0.1:8000/docs>

執行測試：

```powershell
pytest -v
```

## 環境變數

| 變數 | 說明 |
|---|---|
| `LINE_CHANNEL_SECRET` | LINE Messaging API 頻道的 Channel secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | 頻道的 Channel access token |

機密只放在 `.env`，不要提交到版控。

## 給 Java 工程師的對照表

| Java | Python |
|---|---|
| Maven / Gradle | pip + `requirements.txt` |
| 每專案獨立依賴 | venv（`.venv`） |
| Spring Boot | FastAPI |
| 內嵌 Tomcat | Uvicorn |
| `@PostMapping` | `@app.post(...)` |
| `application.yml` | `.env` + python-dotenv |
| JUnit | pytest |

## 授權

尚未指定。
