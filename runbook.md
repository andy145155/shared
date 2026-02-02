This is a much better way to document the security model for engineering teams. It acts as a clear "build spec" for whoever writes the Terraform.

Here is the replacement section. You can swap out **Section 3: Authentication & Security Design** in the System Design document with this detailed specification.

---

## 3. IAM & IRSA Configuration Specification

This section details the specific Identity and Access Management (IAM) resources required. The architecture follows a Hub-and-Spoke model where the Kubernetes Service Account (in the Hub) assumes roles in the target accounts (Spokes).

### A. Hub Account Resources (IRSA Identity)

*These resources are deployed in the Security Control Account (Hub) where the EKS cluster resides.*

#### 1. Kubernetes Service Account (The "Trigger")

* **Resource Type:** Kubernetes Manifest
* **Location:** EKS Cluster (Namespace: `security-compliance`)
* **Name:** `report-generator-sa`
* **Configuration:** Must include the annotation mapping it to the IAM Role.
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: report-generator-sa
  namespace: security-compliance
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::[HUB_ACCOUNT_ID]:role/system-config-report-generator-write-role

```



#### 2. IRSA IAM Role (The "Hub Identity")

* **Resource Type:** AWS IAM Role
* **Location:** Hub Account (`ptdev-sec-control` / `prod-sec-control`)
* **Role Name:** `system-config-report-generator-write-role`
* **Trust Policy (Principal):** Federated OIDC (Not Lambda, Not EC2).
```json
{
  "Effect": "Allow",
  "Principal": {
    "Federated": "arn:aws:iam::[HUB_ACCOUNT_ID]:oidc-provider/[EKS_OIDC_ID]"
  },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {
      "[EKS_OIDC_ID]:sub": "system:serviceaccount:security-compliance:report-generator-sa"
    }
  }
}

```


* **Permissions Policy:**
* **Action:** `sts:AssumeRole`
* **Resource:** `arn:aws:iam::*:role/system-config-report-generator-read-role` (Wildcard allows assuming the role in *any* spoke account).
* **Action:** `s3:PutObject`, `s3:GetBucketLocation`
* **Resource:** `arn:aws:s3:::s3-config-compliance-reports/*`



---

### B. Spoke Account Resources (Target Access)

*These resources are deployed in EVERY AWS account that needs to be audited.*

#### 3. Cross-Account Read Role (The "Spoke Identity")

* **Resource Type:** AWS IAM Role
* **Location:** All Target Accounts (Spokes)
* **Role Name:** `system-config-report-generator-read-role`
* **Trust Policy (Principal):** The Hub Account's Role.
```json
{
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::[HUB_ACCOUNT_ID]:role/system-config-report-generator-write-role"
  },
  "Action": "sts:AssumeRole"
}

```


* **Permissions Policy:** (Read-Only Audit Access)
* **Config:** `config:DescribeConfigRules`, `config:DescribeConfigurationRecorders`, `config:GetComplianceDetailsByConfigRule`
* **EC2:** `ec2:DescribeInstances`, `ec2:DescribeSecurityGroups`, `ec2:DescribeSubnets`, `ec2:DescribeVpcs`, `ec2:DescribeTags`
* **IAM:** `iam:ListRoles`, `iam:ListUsers`, `iam:ListPolicies`
* **RDS:** `rds:DescribeDBClusters`, `rds:DescribeDBInstances`
* **CloudFront:** `cloudfront:ListDistributions`
* **API Gateway:** `apigateway:GET`



---

### C. Organization Management Resources (Discovery)

*These resources are deployed ONLY in the Organization Management Account (Root).*

#### 4. Org Discovery Role

* **Resource Type:** AWS IAM Role
* **Location:** Organization Management Account (`root-org-master`)
* **Role Name:** `system-config-report-generator-list-org-role`
* **Trust Policy (Principal):** The Hub Account's Role.
```json
{
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::[HUB_ACCOUNT_ID]:role/system-config-report-generator-write-role"
  },
  "Action": "sts:AssumeRole"
}

```


* **Permissions Policy:**
* **Organizations:** `organizations:ListAccountsForParent`, `organizations:ListOrganizationalUnitsForParent`