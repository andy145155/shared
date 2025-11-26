# PLC-004: Istio Release Runbook

* **Background**
* **CIA**
* **References**
* **Prerequisites**
* **Process Steps**
    * Pre-actions (IAM & Images)
    * Apply Release Changes (Non-Prod vs Prod)
    * Execution (ArgoCD Sync)
    * Verification
    * Post-actions
* **Rollback Plan**

---

### Background
To provide a standardized, repeatable procedure for releasing a new version of the Istio service mesh in a controlled manner.
* **Goal:** Zero-downtime upgrade of Control Plane (`istiod`) and Data Plane (Sidecars/Gateways).
* **Strategy:** Canary upgrade using ArgoCD (Dual Control Plane).

---

### CIA
Describe potential impacts based on [Change Impact Analysis Standard]

| Impact type | Change requirements |
| :--- | :--- |
| **No customer impact** | • **HW Change Required**<br>• [Disrupts existing customer workloads] risk is managed via Canary upgrade.<br>• **Note:** Potential momentary 5xx errors during sidecar rotation. |

---

### References

| Item | Details |
| :--- | :--- |
| **Owner (Squad)** | Application Foundation (@Cindy Ng @Dave Lui @Day Yeung @Martin Kiesel @Nick Chan @Titus Chu) |
| **Change Type** | [HWC (heavy weight change)] |
| **System Documentation** | [Architecture diagrams, service docs] |
| **Monitoring & Dashboards** | [Datadog: AF Service Version Tracking]<br>[TMV Grafana Dashboard] |
| **Repos** | `platform-docker-images` (Images)<br>`argocd-apps` (Config)<br>`terraform-aws-eks-cluster` (IAM) |
| **Escalation** | Slack: `#squad-platform-foundation` |

---

### Prerequisites
Before running this procedure, ensure the following are in place:
* **Access:** VPN, `kubectl` access to target clusters, ArgoCD apply access.
* **Tools:** `kubectl`, `istioctl` (matching target version).
* **Dependencies:** Other services or teams that must be aligned.
* **Safety Checks:** Confirm backups, failover, readiness, approvals in place.
* **Notify stakeholders:**
    * Align with `#squad-core-banking` on `tm-vault` cluster Istio deployment timeline.

---

### Process Steps

#### 1. Pre-actions

**Verify IAM Policy**
* Update the IAM policy if the application requires additional permissions.
    * *Example:* `terraform-aws-eks-cluster`: AF-5871: Update IAM policy aws-loadbalancer-controller.
    * *Check:* `rbac_sa_external_dns.tf`

**Prepare Docker Image**
* Build and push image with the updated version in the `ProjectDrgn/platform-docker-images`.
* Review previous PRs for guidance on expected changes and validation approach.
    * *Ref:* `platform-docker-images`: PLOPS-368 / PLOPS-393.
* **Warning:** If Snyk errors occur during build, follow the [Image Patching Process] for resolution.

#### 2. Apply Release Changes (Workflow)

**A. Non-prod (PTDEV)**
1.  Create a branch and update the version or config in `values.yaml`.
2.  **Test in `ptdev` before promotion:**
    * Push your commit changes *directly* to the `ptdev` branch.
    * Release new `ptdev` resources via ArgoCD -> follow **Execution** section below.
    * Validate services in `ptdev` -> follow **Verification** section below.
3.  Once validation passes, submit a PR that includes non-prod changes.
    * *Note:* Always use latest chart version bump.
    * *Ref:* `argocd-apps`: PLOPS-393 (Train 4 non-prod).

**B. Prod (STG / PROD)**
1.  Create a branch and update the prod version or config in `values.yaml`.
2.  Confirm all non-prod environments have passed verification steps.
3.  Submit a change ticket according to the **Change Type** before promoting to prod.
4.  Create a PR that includes:
    * Apply version or configuration changes.
    * Clear description with links to: **Change ticket**, **Evidence of non-prod PR**, **Related Jira task**.
    * *Ref:* `argocd-apps`: PROD-41427 (Train 4 PROD).

---

#### 3. Execution (ArgoCD Sync)

**Go to deployment resources and open the ArgoCD link for your app.**

**Step 1: `istio-base` upgrade**
1.  After merging the version bump PR to the main branch, confirm that the **SYNC STATUS** shows `OutOfSync` (yellow).
2.  Click **DIFF** to confirm that the manifest reflects your intended changes.
3.  Click **SYNC** (Ensure "Prune" is **DISABLED**).
4.  Wait until the sync is complete and verify that the app health status returns to **Healthy**.

**Step 2: `istiod` upgrade**
1.  Repeat the sync process for the `istiod` application.
2.  **Note:** It is expected to see `OutOfSync` as old `istiod` components should handle Istio-enabled services with old proxies.
3.  Wait until app status is **Healthy**.

**Step 3: Sidecar Rotation (Apply new version to workloads)**
*Do either (a) Restart Services or (b) EKS Node Rolling*

* **(a) Restart Istio enabled services:**
    1.  Go to `af-toolkit` in ArgoCD.
    2.  Locate job: `sequential-restart-all-istio-enabled-services`.
    3.  **Sync the Job Only:** Click the options (three dots) on the job -> Sync -> **Force Enabled**.
    4.  *Warning:* DO NOT sync the entire `af-toolkit` app.
* **(b) EKS Node Rolling:**
    1.  If performing alongside EKS upgrade, proceed with Node Group rollout.

---

#### 4. Verification

| Action | Expected Result | Env | Notes |
| :--- | :--- | :--- | :--- |
| **[Review service logs]** | [No errors or critical warnings] | [STG] | Check `istiod` logs for `error` or `warn`. |
| **[Check services health]** | [All endpoints return success (200/OK)] | [PTDEV, PROD] | Ensure no pods are stuck in `CrashLoopBackOff`. |
| **[Test Whitelist]** | `curl -vvv template-service...` returns **200 OK** | [STG] | Verify AuthorizationPolicy allows traffic. |
| **[Test Blocklist]** | `curl -vvv mf-trading-service...` returns **403 Forbidden** | [STG] | Verify RBAC denies traffic ("access denied"). |
| **[Verify alerts]** | [No new alerts triggered] | [STG, PROD] | Confirm in Datadog/PagerDuty. |
| **[Promotion wait period]** | [STG environment remains stable for at least X days/weeks] | [STG] | Required before PROD rollout. |

---

#### 5. Post-actions
* [Remove maintenance mode (if enabled)]
* [Verify monitoring alerts remain quiet]
* **[Prune Old Control Plane]:** Once verification is complete, Sync `istiod` with **Prune ENABLED** to remove legacy versions.
* [Update status in Jira/Confluence/Ticket as complete]
* [Capture issues / improvements]

---

### Rollback Plan
*[Emergency Revert Procedure]*

Describe how to safely return the system to its previous state if this change fails.

1.  **Revert Git Changes:**
    * Revert the PR in `argocd-apps` (restore `values.yaml` to previous version).
2.  **Sync ArgoCD:**
    * Sync `istio-base` and `istiod` to the reverted version.
3.  **Restart Sidecars:**
    * Rerun the `sequential-restart-all-istio-enabled-services` job in `af-toolkit` (with **Force**) to inject the old proxy version back into workloads.
4.  **Verify Rollback:**
    * Reuse the **Verification** table steps above (specifically the `curl` commands) to ensure traffic flow is restored.