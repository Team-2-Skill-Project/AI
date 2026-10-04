FROM python:3.11-slim AS builder 

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim 

RUN apt-get update && \
    apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/sh -d /app appuser 

WORKDIR /app

COPY --from=builder --chown=appuser:appgroup /opt/venv /opt/venv 
ENV PATH="/opt/venv/bin:$PATH"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

COPY --chown=appuser:appgroup . . 

USER appuser

EXPOSE 8001

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]

