Here is the migrated runbook following your new standard template, with all API token-related steps stripped out so it focuses purely on the initial admin password rotation.

---

# PLC-011: Rotate TFE Initial Admin Password

## Background

Terraform Enterprise (TFE) is part of the Annual Governance Check on Password Management for Critical Systems. As per compliance requirements, Core Foundation must rotate the initial admin password every 12 months.

This runbook outlines the steps to safely rotate the TFE initial admin password, update it in AWS Secrets Manager, and verify the changes.

## CIA

Describe potential impacts based on Change Impact Analysis Standard.

| Impact type | Change requirements |
| --- | --- |
| **[Disrupts existing customer workloads]**<br>

<br>N/A - This is an administrative credential rotation and does not impact active infrastructure deployments. | **[HW Change Required]** N/A<br>

<br>**[Change After-9pm Required]** N/A<br>

<br>**[Block Mox login]** N/A |

## References

| Category | Details |
| --- | --- |
| **Owner (Squad)** | Core Foundation |
| **Change Type** | STD (standard change) |
| **Change Driver** | Annual Governance Check on Password Management |
| **System Documentation** | 4.6 System Owner Guide: Password Management on Systems |
| **Monitoring & Dashboards** | N/A |
| **Release Notes / Change Logs** | N/A |
| **GitHub Resources** | N/A |
| **JIRA Tickets** | [Insert relevant Governance/Security ticket] |
| **Deployment Resources** | TFE UI, AWS Secrets Manager |
| **Asset Tracking** | N/A |
| **Escalation Channels** | Head of Platform (for break glass access) |

## Prerequisites

Before running this procedure, ensure the following are in place:

* **[Access]**:
* AWS Role: `staff-tfe-bau-admin-role` for PROD (`prod-primary-crossenv`) / PTDEV (`ptdev-primary-crossenv`).


* **[Tools]**:
* AWS Secrets Manager (to obtain and update TFE admin credentials).


* **[Dependencies]**:
* Contact the **TFE MFA Token Owner** to support the login process.


* **[Safety Checks]**: N/A
* **[Notify stakeholders]**: N/A

## Process Steps

### Pre-actions

1. Open the AWS Web console, navigate to **Secrets Manager**, and search for the `tfe-admin` phrase.
2. Back up the current secret values to your local machine (you will delete these later). Specifically, locate:
* PTDEV: `ap-east-1-ptdev-global-tfe-admin-credentials`
* PROD: `ap-east-1-prod-global-tfe-admin-credentials`



### Execution

1. Log into TFE with admin access using the username `projectdrgn-init-admin-user-1`. *(Note: Coordination with the MFA Token Owner is required).*
2. Navigate to the user icon (top right)  **Account Setting**  **Password**.
3. Enter the current password and the new password, then click **Change password**.
> **Note:** As per the System Owner Guide, the password must be **over 15 characters with complexity** to maintain the annual rotation process. Otherwise, a bi-annual rotation will be enforced. Changing the password will invalidate browser sessions and require you to log in again.


4. Update the secret values back in AWS Secrets Manager with the newly generated password:
* **ptdev**: Update `ap-east-1-ptdev-global-tfe-admin-credentials`
* **prod**: Update `ap-east-1-prod-global-tfe-admin-credentials`



### Verification

| Action | Expected Result | Environment(s) to Verify | Notes |
| --- | --- | --- | --- |
| [Log in to TFE] | [Successfully authenticate into TFE] | [PTDEV, PROD] | [Requires coordination with MFA Token Owner] |
| [Check Secrets Manager] | [New password value is saved securely] | [PTDEV, PROD] | [Ensure no trailing spaces in the secret] |

### Post-actions

* **[Governance Update]**: Update the "Completed ticket" and "New ticket" details on the *Annual Governance Check on Password Management - Critical Systems* Confluence page.
* **[Clean up]**: Remove the old, backed-up secret values from your local machine.

## Rollback Plan

If the password rotation fails or secrets are accidentally deleted, follow these steps to restore access:

* **If the AWS Secret was overwritten incorrectly or deleted:**
You can restore the previous value of the secret using the AWS CLI.
```bash
aws secretsmanager update-secret-version-stage \
  --secret-id <SecretName> \
  --version-stage AWSCURRENT \
  --move-to-version-id <OldVersionId> \
  --remove-from-version-id <BadVersionId>

```


* **If both the initial admin user password and the MFA token are lost:**
Raise a request to the Head of Platform for approval of break-glass access. The Squad lead will guide you through the break-glass document to recover the initial admin user.

---

Would you like me to help format the extracted API token steps into a separate runbook, assuming you might be automating that portion?