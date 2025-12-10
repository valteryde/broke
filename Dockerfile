FROM python:3.13
WORKDIR /usr/local/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY run.py ./run.py

# Create directory for data and give ownership to app user
RUN useradd --create-home app && \
    mkdir -p /data && \
    chown -R app:app /data

USER app

EXPOSE 8080
ENV DATA_PATH=/data

# Migrate the database on startup
RUN python scripts/migrate.py

CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:8080"]
