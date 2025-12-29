Here is the updated **README.md** section.

I have rewritten it to reflect your **Decoupled** structure (where each folder is an independent project) and added the details about the new Governance checks.

---

### 📦 Dependency Management (uv)

We have migrated from `requirements.txt` to **[uv](https://github.com/astral-sh/uv)** for faster, deterministic, and secure dependency management.

Each tool in this repository (`verification-external-dns`, `ecr-cleanup`, etc.) is an **independent project** with its own `pyproject.toml` and `uv.lock`.

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

Because projects are decoupled, you must manage dependencies inside each tool's folder.

**Initial Setup for a Tool:**

```bash
cd verification-external-dns
uv sync

```

*This creates a `.venv` inside that specific folder.*

**Running Scripts:**
You do not need to manually activate the virtual environment. Use `uv run` to execute commands using that folder's environment.

```bash
# Run the script
uv run verification_external_dns.py

# Run tests
uv run pytest

```

**Adding New Libraries:**

```bash
cd verification-external-dns
uv add boto3

```

*This automatically updates `pyproject.toml` and regenerates `uv.lock`.*

#### 3. Docker Implementation

We use a standard multi-stage build pattern that respects the lockfile. Since projects are independent, the Dockerfile is self-contained.

**Standard Pattern:**

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# 1. Copy dependency definitions
COPY pyproject.toml uv.lock ./

# 2. Sync dependencies (frozen ensures lockfile match)
RUN uv sync --frozen --no-dev --no-install-project

# 3. Enable the environment
ENV PATH="/app/.venv/bin:$PATH"

# 4. Copy source code
COPY scripts/ .

CMD ["python", "main.py"]

```

#### 4. CI/CD Governance

We enforce strict dependency policies in GitHub Actions. Your PR will fail if:

1. **Forbidden Files:** You commit a `requirements.txt` file (delete it and use `uv add -r ...` to migrate).
2. **Missing Lockfile:** You commit `pyproject.toml` but forget `uv.lock`.
3. **Stale Lockfile:** Your `uv.lock` does not match `pyproject.toml`.
* *Fix:* Run `uv lock` locally and push the changes.



#### ⚠️ Troubleshooting: SSL / Corporate Proxy

If you encounter `invalid peer certificate: UnknownIssuer` errors:

**Option A: Use System Python (Recommended)**
Install Python via Homebrew and tell `uv` to use it instead of downloading a managed version.

```bash
brew install python@3.12
cd ecr-cleanup
uv venv --python 3.12
uv sync

```

**Option B: Trust Custom Certificates**
Export the corporate certificate bundle before running commands:

```bash
export SSL_CERT_FILE=/path/to/zscaler_cert.pem
uv sync

```