Here is the updated, industry-standard `README.md` template.

I have updated it to include:

* **Modular "Execution Context" sections**: You can keep/remove sections depending on if the script runs on ArgoCD, locally only, or both.
* **Useful Links**: A dedicated area for Runbooks and Container Registry links.
* **Troubleshooting**: A standard table to capture common failure modes (a lifesaver for on-call engineers).
* **`uv` Specifics**: Explicit commands for running with environment variables.

---

### 📝 How to use this template

1. Copy the code block below into your `README.md`.
2. Replace any text inside `[...]` with your specific details.
3. **Delete** sections that don't apply (e.g., if it's a local-only script, delete the "ArgoCD" section).

---

```markdown
# [Script / Tool Name]

> [One-sentence summary. E.g. "Automated verification script for external-dns release candidates."]

## 🔗 Useful Links
* **Runbook:** [Link to Notion/Confluence Runbook]
* **Container Image:** `[ghcr.io/org/image-name:tag]`
* **Related Repo:** [Link to related Infrastructure or Config repo]
* **[Other Link]:** [Link]

## 📖 Overview
[Brief paragraph. What problem does this solve? Who uses it?]

**Key Capabilities:**
* [Feature 1]
* [Feature 2]

## 🧠 How It Works
[Briefly describe the logic flow. Keep it high-level.]

1.  **Init:** [e.g., Load config from Env Vars and authenticate to K8s.]
2.  **Action:** [e.g., Deploys a test pod.]
3.  **Validation:** [e.g., Polls API for X seconds.]
4.  **Result:** [e.g., Exits 0 on success, 1 on failure.]

---

## ⚙️ Configuration
This tool is configured via Environment Variables.

| Variable | Description | Required | Default |
| :--- | :--- | :--- | :--- |
| `TARGET_ENV` | Target environment (`dev`, `staging`, `prod`) | **Yes** | - |
| `LOG_LEVEL` | Logging verbosity (`INFO`, `DEBUG`) | No | `INFO` |
| `[CUSTOM_VAR]` | [Description] | [Yes/No] | [Value] |

---

## 🚀 Execution Context
*[Select the sections below that apply to your script and delete the others]*

### [Option A: ArgoCD Hook]
This script is designed to run automatically as an **ArgoCD PostSync Hook**.
* **Trigger:** Runs automatically after syncing `[Application Name]`.
* **Location:** Defined in `[path/to/manifest.yaml]`.
* **Logs:** View logs in the ArgoCD UI under the "Job" resource.

### [Option B: Local Script]
This script is intended to be run manually by engineers for [adhoc tasks / debugging].

---

## 💻 Local Development & Usage

### Prerequisites
* **Language:** [Python 3.12+ (managed by `uv`) / Go 1.21+ / Bash]
* **Access:** Valid AWS credentials and `kubectl` context for the target cluster.

### Running with `uv` (Python)
We use `uv` for execution. No manual virtualenv activation is required.

**1. Basic Run:**
```bash
uv run main.py

```

**2. Running with Environment Variables:**
You can pass variables inline or use a `.env` file.

*Using inline flags (One-off):*

```bash
TARGET_ENV=dev LOG_LEVEL=DEBUG uv run main.py

```

*Using a .env file (Recommended):*

```bash
# 1. Create .env
echo "TARGET_ENV=dev" > .env

# 2. Run with env file
uv run --env-file .env main.py

```

### [Alternative: Go / Bash]

*[Delete if using Python]*

```bash
# Go
go run main.go

# Bash
./scripts/run.sh

```

---

## 🔐 Permissions

To run successfully, the environment (local or remote) needs the following permissions.

**AWS IAM:**

* `[Service/Role Name]`
* **Actions:** `[e.g., route53:ListHostedZones, s3:GetObject]`

**Kubernetes RBAC:**

* **Resources:** `[e.g., Deployments, Services]`
* **Verbs:** `[e.g., get, list, create, delete]`

---

## ❓ Troubleshooting

| Error Message / Symptom | Possible Cause | Solution |
| --- | --- | --- |
| `[Example: 403 Forbidden]` | [Missing IAM role or expired token] | [Run `aws sso login` or check IRSA role] |
| `[Example: Timeout waiting for X]` | [Network policy or delay in propagation] | [Check VPC settings or increase `TIMEOUT_SEC`] |

---

## 📝 Notes & Future Work

*[Optional: Add any tech debt, known limitations, or future plans here]*

* [Note 1]
* [Note 2]

```
[Add any additional sections below as needed, e.g., ## Architecture Diagram, ## Release Process]
```