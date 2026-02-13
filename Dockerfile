FROM python:3.13
WORKDIR /usr/local/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY run.py ./run.py
COPY docker-entrypoint.sh ./docker-entrypoint.sh
# Copy the pyproject file 
COPY pyproject.toml ./pyproject.toml

# Create directory for data and give ownership to app user
RUN useradd --create-home app && \
    mkdir -p /data && \
    chown -R app:app /data && \
    chown -R app:app /usr/local/app && \
    chmod +x docker-entrypoint.sh

USER app

EXPOSE 8080
ENV DATA_PATH=/data

# Run migration and then start the server
CMD ["./docker-entrypoint.sh"]
