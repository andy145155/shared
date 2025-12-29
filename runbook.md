Here is a comprehensive Markdown section you can add to your `README.md`.

It covers the entire workflow: setting up the workspace locally, handling the corporate proxy/SSL issues you just encountered, adding dependencies to specific sub-projects, and deploying via Docker and GitHub Actions.

---

### 📦 Dependency Management (uv)

We use **[uv](https://github.com/astral-sh/uv)** to manage Python dependencies, virtual environments, and package resolution. It replaces `pip`, `virtualenv`, and `requirements.txt`.

This repository is set up as a **uv Workspace**, meaning we have one lockfile (`uv.lock`) in the root that manages versions for all sub-projects (`verification-external-dns`, `verification-istio`, etc.) simultaneously.

#### 1. Installation

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh

```

*Or via Homebrew:*

```bash
brew install uv

```

#### 2. Local Development

##### Initial Setup

To set up the environment for **all** tools in the repo at once:

```bash
uv sync

```

This creates a central virtual environment at `.venv` in the root directory.

##### Running Scripts

You do not need to manually activate the virtual environment. Use `uv run` from anywhere in the repo:

```bash
# Run a script inside the 'verification-external-dns' folder
uv run verification-external-dns/verification_external_dns.py

# Run a test using the shared environment
uv run pytest

```

##### Adding Libraries

Since this is a workspace, you must specify *which* tool needs the library.

**Don't do this:** `uv add boto3` (this adds it to the root, which is usually wrong).
**Do this:**

```bash
# Add 'boto3' specifically to the external-dns tool
uv add boto3 --package verification-external-dns

```

#### ⚠️ Troubleshooting: SSL / Corporate Proxy Issues

If you see `invalid peer certificate: UnknownIssuer` or connection errors when running `uv sync` or installing Python:

**Option A: Use System Python (Recommended for Corporate Devices)**
Install Python via Homebrew (which handles certificates better) and tell `uv` to use it instead of downloading its own.

```bash
brew install python@3.12
uv venv --python 3.12
uv sync

```

**Option B: Trust Custom Certificates**
Export your corporate certificate bundle before running commands:

```bash
export SSL_CERT_FILE=/path/to/corporate-cert.pem
uv sync

```

---

#### 3. Docker Implementation

In a workspace, Docker builds are slightly different because `uv.lock` is in the root. We use a multi-stage build to keep images small.

**Example `Dockerfile` for a sub-project:**

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# 1. Copy the ROOT workspace files first
COPY pyproject.toml uv.lock ./

# 2. Copy the specific tool's configuration
COPY verification-external-dns/pyproject.toml ./verification-external-dns/

# 3. Install dependencies ONLY for this specific tool
# --package selects just this workspace member
RUN uv sync --frozen --no-install-project --package verification-external-dns

# --- Final Stage ---
FROM python:3.12-slim-bookworm

WORKDIR /app

# Copy the environment from builder
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY verification-external-dns/ .

CMD ["python", "verification_external_dns.py"]

```

#### 4. GitHub Actions (CI/CD)

We use the official `setup-uv` action which handles caching automatically (making builds extremely fast).

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version-file: "pyproject.toml"

      - name: Install Dependencies
        run: uv sync --all-extras --dev

      - name: Run Tests
        run: uv run pytest

```