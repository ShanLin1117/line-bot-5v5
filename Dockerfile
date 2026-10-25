FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先只複製依賴清單再安裝：程式碼改動時可以重用這一層快取，建置比較快
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 資料庫放在 /data，部署時由平台掛載持久化磁碟
ENV DB_PATH=/data/line-bot.db
VOLUME /data

EXPOSE 8000

# 只能跑單一 worker（不要加 --workers）：排程跑在程式裡，多個 worker 會各開一份
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
