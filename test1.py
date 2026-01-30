import boto3
from botocore.exceptions import ClientError

# Constants
ROLE_TO_ASSUME = "OrganizationAccountAccessRole"  # Ensure this role exists in target accounts
ROOT_ID = "r-u5jv"  # From your orgmaster.py

def get_assumed_session(account_id, region="us-east-1"):
    """
    Returns a boto3 Session authenticated into the target account using IAM Roles.
    """
    sts = boto3.client('sts')
    role_arn = f"arn:aws:iam::{account_id}:role/{ROLE_TO_ASSUME}"
    
    try:
        response = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName="ComplianceLambdaSession"
        )
        creds = response['Credentials']
        return boto3.Session(
            aws_access_key_id=creds['AccessKeyId'],
            aws_secret_access_key=creds['SecretAccessKey'],
            aws_session_token=creds['SessionToken'],
            region_name=region
        )
    except ClientError as e:
        print(f"ERROR: Could not assume role in {account_id}: {e}")
        return None

def get_all_accounts_with_ou():
    """
    Traverses AWS Organizations to find all active accounts and their OUs.
    Replaces Orgmaster.get_accounts()
    """
    org = boto3.client('organizations')
    accounts_list = []
    
    # 1. Get all OUs under the root
    # Note: If you have nested OUs (OUs inside OUs), you might need a recursive function here.
    # For now, this matches your orgmaster.py logic (single level under root).
    paginator = org.get_paginator('list_organizational_units_for_parent')
    ous = []
    for page in paginator.paginate(ParentId=ROOT_ID):
        ous.extend(page['OrganizationalUnits'])
        
    # 2. For each OU, get the accounts
    for ou in ous:
        ou_id = ou['Id']
        ou_name = ou['Name']
        
        acc_paginator = org.get_paginator('list_accounts_for_parent')
        for page in acc_paginator.paginate(ParentId=ou_id):
            for acc in page['Accounts']:
                if acc['Status'] == 'ACTIVE':
                    accounts_list.append({
                        'Id': acc['Id'],
                        'Name': acc['Name'],
                        'OU': ou_name
                    })
                    
    return accounts_list