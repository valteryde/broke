FROM python:3.13
WORKDIR /usr/local/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server .

# Create directory for data and give ownership to app user
RUN useradd --create-home app && \
    mkdir -p /data && \
    chown -R app:app /data

USER app

EXPOSE 8080
ENV DATA_PATH=/data

CMD ["gunicorn", "server:app", "--bind", "0.0.0.0:8080"]
