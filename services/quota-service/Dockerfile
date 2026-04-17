FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV QUOTA_HOST=0.0.0.0
ENV QUOTA_PORT=8003

EXPOSE 8003

CMD ["python", "-m", "quota_service.main"]
