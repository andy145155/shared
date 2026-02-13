Based on the runbook screenshots you provided, here is a drafted Jira ticket focused exclusively on automating the **API Token** rotation.

I have extracted the specific secret names, workspace details, and naming conventions from your images to make this actionable.

---

## **Jira Ticket: Automate TFE Admin API Token Rotation**

### **Description**

Currently, the "Annual Governance Check" for TFE requires a manual rotation of the initial admin API tokens. This process involves logging into the UI, generating tokens manually, and updating multiple downstream systems (AWS Secrets Manager and TFE Workspaces).

We want to automate this process to reduce toil and eliminate the risk of copy-paste errors during the annual (or bi-annual) rotation.

**Current Manual Workflow (to be automated):**

1. **Generate Tokens:** Create two new API tokens for the `initial admin` user:
* `api-cancel-run-[yyyymm]` (Used by the `tfe-cancel-non-head-commit-plan` Lambda)
* `platform-terraform-[yyyymm]` (Used by the `platform-terraform` TFE workspace)


2. **Update AWS Secrets Manager:** Update the secret `ap-east-1-[env]-crossenv-tfe-admin-api-token` with the new values.
3. **Update TFE Workspace:** Update the sensitive environment variable `TFE_TOKEN` in the `platform-terraform-[env]` workspace.

### **Technical Scope**

Develop a script or Lambda function that performs the following via the TFE and AWS APIs:

1. **Authentication:** Authenticate as the TFE Admin.
2. **Token Creation:** Generate the two required user tokens with the `[yyyymm]` suffix.
3. **Secret Sync:**
* Push the new `api-cancel-run` token to AWS Secrets Manager (`ap-east-1-[env]-crossenv-tfe-admin-api-token`).


4. **Workspace Sync:**
* Push the new `platform-terraform` token to the `platform-terraform-[env]` workspace as the `TFE_TOKEN` variable.


5. **Cleanup (Optional):** Identify and revoke tokens older than the previous rotation period.

### **Configuration Details**

* **Target Environments:** `ptdev`, `prod`
* **AWS Role:** `staff-tfe-bau-admin-role`
* **Secret Name:** `ap-east-1-[env]-crossenv-tfe-admin-api-token`
* **Target Workspace:** `platform-terraform-[env]`

### **Acceptance Criteria**

* [ ] **Automation Script Created:** A script/function exists that can generate valid TFE user tokens.
* [ ] **Naming Convention Enforced:** Tokens are generated with the correct `[yyyymm]` suffix for auditability.
* [ ] **AWS Secret Updated:** The script successfully updates the specific keys in AWS Secrets Manager without manual intervention.
* [ ] **TFE Variable Updated:** The `TFE_TOKEN` in the platform workspace is updated automatically.
* [ ] **Verification:** The new tokens are verified by:
* Successfully triggering a dummy run in `platform-terraform-[env]`.
* Successfully triggering the `tfe-cancel-non-head-commit-plan` Lambda.



---

**One question for you:**
The runbook mentions that `api-cancel-run` and `platform-terraform` are separate tokens to isolate TFE from AWS compromise. Does the automation need to keep these strictly separate (generating two distinct tokens), or is it acceptable to use a single token for both if we are automating the rotation frequently? (The ticket above assumes we keep them separate to match the current security posture).