Here is a comprehensive PR description ready to copy and paste.

---

**Title:** chore: migrate dependency management to uv & add governance checks

### 📝 Summary

This PR modernizes our Python dependency management by migrating from `requirements.txt` to **[uv](https://github.com/astral-sh/uv)**.

We are moving to a **decoupled project structure** where each tool (e.g., `ecr-cleanup`, `verification-external-dns`) maintains its own `pyproject.toml` and `uv.lock`. This ensures deterministic builds, faster CI times, and better isolation between tools.

### 🛠️ Key Changes

**1. Dependency Migration**

* Removed `requirements.txt` from all tool subdirectories.
* Initialized `pyproject.toml` for each tool and generated strict `uv.lock` files to pin dependencies.
* *Tools affected:* `verification-external-dns`, `ecr-cleanup`, `verification-istio`, etc.

**2. Docker Optimization**

* Updated Dockerfiles to use `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` as the base builder.
* Replaced `pip install` with `uv sync --frozen` for faster, cached installation.
* Ensured Zscaler certificate compatibility within the `uv` build process.

**3. CI/CD Governance**

* Added a new GitHub Action: `.github/workflows/enforce-uv.yaml`.
* **Policy Enforced:**
* Fails if any tracked `requirements.txt` file is found.
* Fails if `uv.lock` is missing or out-of-sync with `pyproject.toml`.



**4. Documentation**

* Updated `README.md` with a new "Dependency Management" section explaining how to use `uv` for local development (sync, run, add) and Docker builds.

### 🚀 Benefits

* **Speed:** Dependency resolution and installation are significantly faster (orders of magnitude over pip).
* **Determinism:** `uv.lock` guarantees that the exact same package versions are used in local dev, CI, and Production.
* **Safety:** The new governance workflow prevents dependency drift and ensures no one accidentally reverts to using `requirements.txt`.

### 🧪 Testing

* [x] **Local:** Verified `uv sync` and `uv run` work inside `verification-external-dns` and `ecr-cleanup`.
* [x] **Docker:** Built images successfully using the new multi-stage Dockerfiles (tested with Zscaler certs).
* [x] **CI:** Verified that the governance action correctly flags missing lockfiles.

### ℹ️ Reviewer Notes

To test this branch locally, you will need to install `uv`:

```bash
brew install uv
# Test a project
cd verification-external-dns
uv sync
uv run verification_external_dns.py

```