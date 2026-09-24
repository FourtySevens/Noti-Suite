FROM python:3.13-slim

WORKDIR /app
COPY scheduler.py /app/scheduler.py

ENV PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/scheduler.db \
    SCHEDULER_BIND=0.0.0.0 \
    SCHEDULER_PORT=8080

EXPOSE 8080
CMD ["python", "/app/scheduler.py"]
