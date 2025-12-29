# Recommended: Use standard slim (Debian) instead of Alpine for better wheel/SSL compatibility
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Add build-time argument to toggle Zscaler support
ARG ENABLE_ZSCALER=false

WORKDIR /app

# --- 1. Certificate Setup (Crucial for uv to work) ---
# Copy certs early so they are available for the install step
COPY ecr-cleanup/scripts/zscaler_2025.pem /usr/local/share/ca-certificates/zscaler_2025.crt

RUN if [ "$ENABLE_ZSCALER" = "true" ]; then \
    echo "Enabling Zscaler certificate support..."; \
    update-ca-certificates; \
    else \
    echo "Skipping Zscaler certificate setup"; \
    fi

# Tell uv (and Python requests) exactly where the bundle is
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# --- 2. Dependency Installation (The uv Way) ---
# Copy the lockfiles (assumes you ran 'uv init' inside ecr-cleanup folder)
COPY ecr-cleanup/pyproject.toml ecr-cleanup/uv.lock ./

# Install dependencies into a virtual environment at /app/.venv
# --frozen: fails if lockfile is out of sync (safety)
# --no-dev: skips test dependencies
# --no-install-project: only installs libraries, not the script itself yet
RUN uv sync --frozen --no-dev --no-install-project

# --- 3. Application Setup ---
# Copy your actual script
COPY ecr-cleanup/scripts/main.py /app/main.py

# Create a non-root user (Debian syntax)
RUN useradd -m app && chown -R app:app /app

# Enable the virtual environment automatically
ENV PATH="/app/.venv/bin:$PATH"

# Run as non-root
USER app
ENTRYPOINT ["python", "main.py"]