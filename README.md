# line-bot-5v5

LINE 群組球賽報名與分組機器人：每週自動開場次，管理員發出報名卡後大家按按鈕報名，季打保障名額、零打依序、候補自動遞補，比賽當天隨機分組。

## 功能（規劃中）

- [x] 專案骨架：FastAPI + LINE Webhook 簽章驗證與回覆訊息
- [x] 群組綁定：只服務一個群組，其他群組自動退出
- [x] 報名規則：季打保障名額、零打依序、候補自動遞補、帶朋友（見 [docs/rules.md](docs/rules.md)）
- [x] 管理指令：開場次、標記季打、管理員
- [x] 加開場：不分季打零打、先搶先贏，與例行場合併在同一張報名卡
- [x] 報名卡片（按鈕）與週日 20:00 自動開場次（不推播，報名卡由管理員傳 `/報名卡` 發出）
- [x] `/分組` 隨機分組（A、B、C、D 隊，結果固定，另有 `/重新分組`）
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
├── teams.py        # 分組（純函式）與結果格式化
├── scheduler.py    # 每週日 20:00 自動開場次（不發訊息）
├── handlers.py     # 指令與按鈕處理（依賴資料庫，不依賴 LINE）
└── line_client.py  # LINE Messaging API 呼叫（回覆、查名稱、退出群組；刻意不使用推播）
docs/rules.md       # 報名規則規格
tests/              # 測試
data/               # SQLite 資料庫檔案（不進版控）
tmp/                # 暫存檔（不進版控）
```

## 使用方式

1. 把 Bot 拉進群組，由**隊長**先傳 `/初始化`，群組即被綁定，隊長成為管理員。
2. 管理員用 `/設定 地點 …`、`/設定 時間 …`、`/設定 費用 …` 設定報名卡資訊。
3. 管理員用 `/成員` 查編號，再用 `/設季打 3 7 12` 標記季打（新季用 `/重設季打` 清除）。
4. 每週日 20:00 Bot 自動開放下週日場次（不發訊息），管理員傳 `/報名卡` 發出報名卡，大家按按鈕報名；也可以用 `/報名`、`/取消` 等指令。
5. 傳 `/名單` 查看正取與候補，傳 `/說明` 看完整指令。要立刻發卡可用 `/報名卡`（回覆，不耗額度），確認排程時間可用 `/排程狀態`，要手動開場次可用 `/開週 10/25`。
6. 比賽當天管理員傳 `/分組`，Bot 把正取名單隨機分隊並公布；結果不會因為再按一次而改變，任何人可用 `/分組結果` 查看，真的要重抽才用 `/重新分組`。
7. 臨時加開場次：`/加開場 11/06 20 晚上7點 中正運動中心`（先搶先贏，不分季打零打），取消用 `/取消加開場 11/06`。加開場的指令在最後加上日期，例如 `/名單 11/06`。

完整規則請看 [docs/rules.md](docs/rules.md)。

## 快速開始

以下為 PowerShell 指令。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt   # 含測試工具；正式環境只需要 requirements.txt
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

## 部署（Fly.io）

Bot 需要一直開著（週日 20:00 排程開場次）、需要保存 SQLite 資料庫、且只能跑**一台**，所以要用有持久化磁碟、不會休眠的平台。以下為 Windows PowerShell 指令。

```powershell
winget install Fly-io.flyctl             # 安裝後重開 PowerShell
flyctl auth login                         # 開瀏覽器登入
flyctl config validate                    # 驗證 fly.toml

# 1. 建立 app（名稱要全站唯一；若不是 line-bot-5v5-shanlin，請同步修改 fly.toml 的 app）
flyctl apps create line-bot-5v5-shanlin

# 2. 建立持久化磁碟（放資料庫），區域要與 fly.toml 的 primary_region 相同
flyctl volumes create data --size 1 --region nrt

# 3. 設定金鑰（請自己在終端機輸入，不要貼到任何對話或檔案）
flyctl secrets set LINE_CHANNEL_SECRET=... LINE_CHANNEL_ACCESS_TOKEN=...

# 4. 部署，--ha=false 確保只有一台機器（不然排程與 SQLite 都會出問題）
flyctl deploy --ha=false
```

部署完成後：

1. 到 LINE Developers Console 的 Messaging API，把 Webhook URL 改成 `https://<app 名稱>.fly.dev/callback` 並按 Verify。
2. 關掉本機的 `uvicorn` 與 `ngrok`，否則會有兩份 Bot。
3. 在群組由隊長傳 `/初始化`，再 `/設季打`、`/設定` 等。**雲端資料庫是全新的**，本機測試資料不會帶過去。

常用指令：

```powershell
flyctl logs                # 看即時 log
flyctl status              # 看機器狀態
flyctl ssh console         # 進入機器（資料庫在 /data/line-bot.db）
flyctl volumes snapshots list data   # 查看磁碟快照（備份）
```

本機驗證映像（需先啟動 Docker Desktop）：

```powershell
docker build -t line-bot-5v5 .
docker run --rm -p 127.0.0.1:8081:8000 -e LINE_CHANNEL_SECRET=dummy -e LINE_CHANNEL_ACCESS_TOKEN=dummy line-bot-5v5
# 另一個視窗：Invoke-WebRequest http://127.0.0.1:8081/health
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
