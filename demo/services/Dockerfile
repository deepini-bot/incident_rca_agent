FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ARG SERVICE
ENV SERVICE_NAME=${SERVICE} PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY common ./common
COPY ${SERVICE}/main.py ./main.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
