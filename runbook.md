# [Tool / Script Name]

> [Brief, one-sentence summary. E.g., "Automated verification suite for ExternalDNS releases."]

## 📖 Overview
[Short paragraph: What problem does this solve? Who is the user?]

**Key Features:**
* [Feature 1]
* [Feature 2]

## 🧠 How It Works
[Briefly explain the logic flow. Keep it high-level.]

1.  **Step 1:** [e.g., Connects to K8s and discovers active pods.]
2.  **Step 2:** [e.g., Validates configuration against allowed values.]
3.  **Step 3:** [e.g., Performs the operation and logs output.]

---

## ⚙️ Configuration
The application is configured via Environment Variables.

| Variable | Description | Required | Default |
| :--- | :--- | :--- | :--- |
| `TARGET_ENV` | Target environment (dev/staging/prod) | **Yes** | - |
| `[VAR_NAME]` | [Description] | [Yes/No] | [Value] |

---

## 💻 Local Execution
*Prerequisites: `uv` (for Python), `kubectl`, `aws-cli`.*

### Python (via `uv`)
We use `uv` for dependency management. No manual virtualenv setup is required.

**1. Create an env file (Optional)**
```bash
# .env
TARGET_ENV=dev
AWS_REGION=ap-east-1