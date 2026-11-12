FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

RUN DEBIAN_FRONTEND=noninteractive apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/*

RUN addgroup --system app && adduser --system --ingroup app app

COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src ./src
COPY bin ./bin
COPY sources.csv ./sources.csv

RUN chmod +x /app/bin/dev /app/bin/test && \
    mkdir -p /app/data /app/reports /app/articles_bruts && \
    chown -R app:app /app/data /app/reports /app/articles_bruts

USER app

CMD ["python", "-m", "src.scheduler"]
