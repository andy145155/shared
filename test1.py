import boto3
from botocore.exceptions import ClientError
from models.config import Config  # Import your existing configuration

# Constants
ROLE_TO_ASSUME = "OrganizationAccountAccessRole"
ROOT_ID = "r-u5jv"  # Matches your orgmaster.py

def get_assumed_session(account_id, region="us-east-1"):
    """
    Returns a boto3 Session authenticated into the target account using IAM Roles.
    """
    # ... (Same as before) ...
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

def get_filtered_accounts():
    """
    Traverses AWS Organizations but applies Config filters (Ignored OUs, Ignored IDs).
    """
    org = boto3.client('organizations')
    accounts_list = []
    
    # 1. Get all OUs under the root
    paginator = org.get_paginator('list_organizational_units_for_parent')
    ous = []
    
    print(f"Fetching OUs under root {ROOT_ID}...")
    for page in paginator.paginate(ParentId=ROOT_ID):
        for ou in page['OrganizationalUnits']:
            # FILTER 1: Check if OU is in the ignore list
            if ou['Name'] in Config.ignored_organizational_units:
                print(f"Skipping OU: {ou['Name']} (Ignored)")
                continue
                
            ous.append(ou)
        
    # 2. For each valid OU, get the accounts
    for ou in ous:
        ou_id = ou['Id']
        ou_name = ou['Name']
        
        acc_paginator = org.get_paginator('list_accounts_for_parent')
        for page in acc_paginator.paginate(ParentId=ou_id):
            for acc in page['Accounts']:
                # FILTER 2: Status check
                if acc['Status'] != 'ACTIVE':
                    continue

                # FILTER 3: Check if Account ID is in the ignore list
                # Note: Config.ignored_accounts are strings, ensure types match
                if acc['Id'] in Config.ignored_accounts:
                    print(f"Skipping Account: {acc['Name']} ({acc['Id']}) - Explicitly Ignored")
                    continue
                
                # If we passed all filters, add it to the list
                accounts_list.append({
                    'Id': acc['Id'],
                    'Name': acc['Name'],
                    'OU': ou_name
                })
                    
    return accounts_list