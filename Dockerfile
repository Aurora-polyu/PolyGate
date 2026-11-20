# Alpine base: the ceAI+ scan rejected python:3.12-slim (Debian 13) for 15 Unknown OpenSSL findings.
FROM --platform=linux/amd64 python:3.12-alpine
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    POLYGATE_DB_FILE=/data/browzine.sqlite3
COPY requirements.txt constraints.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY browzine_mock ./browzine_mock
COPY data/mock_data.json ./data/mock_data.json
# Make the app files readable by UID 65532 whatever permissions the uploaded ZIP gave them.
RUN chmod -R a+rX /app
# The platform runs apps as UID/GID 65532; write only to /data and /tmp.
# Create /data owned by that user so a fresh named volume is writable.
RUN mkdir /data && chown 65532:65532 /data
USER 65532:65532
EXPOSE 8000
CMD ["python", "-m", "browzine_mock", "serve", "--host", "0.0.0.0", "--port", "8000"]
