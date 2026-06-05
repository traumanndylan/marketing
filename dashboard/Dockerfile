FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /home/dylan/marketing/main /home/dylan/marketing/cron /home/dylan/marketing/postProcessing

COPY . .

EXPOSE 5001

CMD ["python", "app.py"]
