This is a refined **Implementation Plan** that incorporates the specific repository paths, ArgoCD workflows, and the Kubernetes/IRSA details from your screenshots.

You can replace your current "Implementation Steps" section with this structured plan.

---

# Implementation Plan

## Phase 1: IAM Foundation (Terraform)

*Objective: Establish the "identity web" required for the Hub-and-Spoke model before any code runs.*

**1. Define Spoke Roles (Read-Only Targets)**

* **Action:** Define the `system-config-report-generator-read-role` IAM policy.
* **Repository:** `ProjectDrgn/terraform-aws-iam-roles`
* **Implementation:** Update the global baseline module to deploy this role to **all** member accounts.
* **Repository:** `ProjectDrgn/terraform-infrastructure-skeleton`
* *Path:* `/common/baseline/global`


* **Promotion Strategy:** `ptdev` → `dev` → `stg` → `prod`

**2. Define Org Discovery Role (Org Master)**

* **Action:** Deploy the `system-config-report-generator-list-org-role` to the Organization Management account.
* **Repository:** `ProjectDrgn/terraform-infra-orgmaster`
* *Path:* `/tree/master/main`


* **Detail:** Ensure the Trust Policy allows the `sec-control` (Hub) account to assume this role.

**3. Define Hub Resources (IRSA & S3)**

* **Action:** Provision the S3 Bucket and the **IAM Role for Service Accounts (IRSA)** in the Security Control account.
* **Repository:** `ProjectDrgn/terraform-infrastructure-skeleton`
* *Path:* `/sec-control/eks/workers` (or equivalent EKS IAM module path)


* **Detail:**
* Create IAM Role `system-config-report-generator-write-role`.
* Configure Trust Relationship to trust the `cybsecops` EKS OIDC provider (specifically for the `security-compliance` namespace).


* **Promotion Strategy:** `ptdev` → `prod`

---

## Phase 2: Application Containerization

*Objective: Convert the local Python script into a deployable Docker artifact.*

**4. Refactor & Dockerize**

* **Action:** Move the Python logic (refactored for K8s) into the platform automation repo and add a `Dockerfile`.
* **Repository:** `ProjectDrgn/platform-automation`
* **Tasks:**
* Add `aws_utils.py` (IRSA logic) and `main.py` (Threaded scanner).
* Create `Dockerfile` (Base: `python:3.11-slim`).
* Setup GitHub Actions/Jenkins to build and push the image to ECR.



---

## Phase 3: Kubernetes Deployment (ArgoCD)

*Objective: Schedule the workload on the EKS cluster.*

**5. Deploy Manifests via ArgoCD**

* **Action:** Create the Kubernetes manifests (CronJob, ServiceAccount, ConfigMap) for the application.
* **Repository:** `ProjectDrgn/argocd-apps`
* *Path:* `/clusters/cybsecops/templates` (or create a new app folder `aws-config-compliance`)


* **Manifest Details:**
* **ServiceAccount:** Annotate with `eks.amazonaws.com/role-arn: ...write-role`.
* **CronJob:** Schedule: `0 9 * * 1` (Weekly). Image: Pull from ECR.


* **Deployment:** Commit changes to trigger ArgoCD sync to the `cybsecops` cluster.

---

## Phase 4: Validation & Cutover

*Objective: Verify the system works end-to-end.*

**6. Verification**

* **Dry Run:** Manually create a Job from the CronJob:
```bash
kubectl create job --from=cronjob/aws-config-compliance manual-test -n security-compliance

```


* **Logs:** Verify IAM assumption logic:
```bash
kubectl logs job/manual-test -n security-compliance -f

```


* **Artifact:** Confirm the `.xlsx` report appears in the S3 bucket.

**7. Go Live**

* Disable the legacy local script.
* Notify stakeholders that reports are now automated via Kubernetes.