FROM python:3.13-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY cli.py .

USER nobody

EXPOSE 9999
CMD ["python", "main.py"]
