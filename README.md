# line-bot-5v5

LINE 群組球賽分組機器人：自動推播每週報名卡、截止報名，並依身高、體重與位置隨機分組，讓各隊戰力均衡。

## 功能（規劃中）

- [x] 專案骨架：FastAPI + LINE Webhook 簽章驗證與回覆訊息
- [x] 群組綁定：只服務一個群組，其他群組自動退出
- [x] 報名規則：季打保障名額、零打依序、候補自動遞補、帶朋友（見 [docs/rules.md](docs/rules.md)）
- [x] 管理指令：開場次、標記季打、管理員
- [x] 報名卡片（按鈕）與週日 20:00 自動開場次、推播
- [ ] `/分組` 隨機分 4 隊
- [ ] 戰力平衡、管理員代取消

## 技術棧

- Python 3.13
- FastAPI + Uvicorn
- line-bot-sdk（v3）
- SQLite（標準函式庫 `sqlite3`）
- pytest

## 專案結構

```
app/
├── main.py         # 程式入口，/health 與 /callback，事件分派與群組檢查
├── config.py       # 讀取 .env 設定
├── models.py       # 資料模型（Member、Week、Entry）
├── db.py           # SQLite 存取層
├── roster.py       # 名單計算與格式化（純函式，核心規則）
├── card.py         # 報名卡（Flex Message JSON）
├── scheduler.py    # 每週日 20:00 自動開場次並推播報名卡
├── handlers.py     # 指令與按鈕處理（依賴資料庫，不依賴 LINE）
└── line_client.py  # LINE Messaging API 呼叫（回覆、推播、查名稱、退出群組）
docs/rules.md       # 報名規則規格
tests/              # 測試
data/               # SQLite 資料庫檔案（不進版控）
tmp/                # 暫存檔（不進版控）
```

## 使用方式

1. 把 Bot 拉進群組，由**隊長**先傳 `/初始化`，群組即被綁定，隊長成為管理員。
2. 管理員用 `/設定 地點 …`、`/設定 時間 …`、`/設定 費用 …` 設定報名卡資訊。
3. 管理員用 `/成員` 查編號，再用 `/設季打 3 7 12` 標記季打（新季用 `/重設季打` 清除）。
4. 每週日 20:00 Bot 自動開放下週日場次並推播報名卡，大家按按鈕報名；也可以用 `/報名`、`/取消` 等指令。
5. 傳 `/名單` 查看正取與候補，傳 `/說明` 看完整指令。要立刻發卡可用 `/報名卡`，要手動開場次可用 `/開週 10/25`。

完整規則請看 [docs/rules.md](docs/rules.md)。

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
