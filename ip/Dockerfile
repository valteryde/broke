FROM python:3.13-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY geo.py update.py main.py .
RUN mkdir -p /data && chown nobody:nogroup /data

USER nobody
EXPOSE 9998
ENV IP_DATA_DIR=/data
CMD ["python", "main.py"]
