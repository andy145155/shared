FROM ghcr.io/astral-sh/uv:python3.14-alpine

# Add build-time argument to toggle Zscaler support
ARG ENABLE_ZSCALER=false

# Copy Zscaler certificate conditionally (Keep exact path from your screenshot)
COPY --chown=app:app ecr-cleanup/scripts/zscaler_2025.pem /tmp/zscaler_2025.pem

# --- CHANGE 1: Copy pyproject.toml and uv.lock instead of requirements.txt ---
# This assumes you ran 'uv init' and 'uv lock' in the ecr-cleanup folder
COPY ecr-cleanup/pyproject.toml ecr-cleanup/uv.lock ./

# --- CHANGE 2: Replace pip install with uv sync ---
# We export SSL_CERT_FILE locally so uv can use the cert you just copied to /tmp
RUN addgroup -S app && adduser -S -G app app \
    && export SSL_CERT_FILE=/tmp/zscaler_2025.pem \
    && uv sync --frozen --no-dev --no-install-project

RUN if [ "$ENABLE_ZSCALER" = "true" ]; then \
    echo "Enabling Zscaler certificate support..."; \
    mkdir -p /usr/local/share/ca-certificates/; \
    cp /tmp/zscaler_2025.pem /usr/local/share/ca-certificates/; \
    chown app:app /usr/local/share/ca-certificates/zscaler_2025.pem; \
    update-ca-certificates; \
    rm /tmp/zscaler_2025.pem; \
    else \
    echo "Skipping Zscaler certificate setup"; \
    rm /tmp/zscaler_2025.pem; \
    fi

# Copy Python script (Keep exact path from your screenshot)
COPY ecr-cleanup/scripts/main.py /app/main.py

RUN chown -R app:app /app

# --- CHANGE 3: Enable the virtual environment uv created ---
ENV PATH="/app/.venv/bin:$PATH"

# Run the application as the non-root user
USER app
WORKDIR /app
ENTRYPOINT ["python", "main.py"]