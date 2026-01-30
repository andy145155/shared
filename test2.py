import sys
import logging
import datetime
import os
import boto3
import concurrent.futures

# Import your existing logic (assuming you keep the models folder)
from models.account import Account
from aws_utils import get_all_accounts_with_ou  # The file we just created above

# Configure Logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET = os.environ.get('S3_BUCKET', 'my-compliance-bucket-name')

def safe_check_compliance(account_data):
    """
    Wrapper to run compliance checks and handle errors.
    """
    # Initialize your existing Account object
    # NOTE: You must update Account.__init__ to NOT require 'aws_profile' anymore
    acc = Account(
        acc_id=account_data['Id'],
        acc_name=account_data['Name'],
        organizational_unit=account_data['OU']
    )
    
    try:
        # Run the check (This calls the refactored logic in account.py)
        # Ensure account.py now uses get_assumed_session() instead of self.aws_profile
        acc.check_compliance() 
        
        if not acc.config_rules:
            # Matches your existing logic for "skipped"
            return (False, acc, "No config rules found")
            
        return (True, acc)
        
    except Exception as e:
        return (False, acc, str(e))

def lambda_handler(event, context):
    logger.info("Fetching accounts from AWS Organizations...")
    
    # 1. Get Accounts (No more Orgmaster class needed)
    raw_accounts = get_all_accounts_with_ou()
    logger.info(f"Discovered {len(raw_accounts)} accounts.")

    results = []
    
    # 2. Run in Parallel (Replaces pathos ProcessPool)
    # Lambda handles threads well. max_workers=20 is usually safe.
    logger.info("Checking compliance in parallel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_acc = {executor.submit(safe_check_compliance, acc): acc for acc in raw_accounts}
        
        for future in concurrent.futures.as_completed(future_to_acc):
            results.append(future.result())

    # 3. Process Results
    successes = [r[1] for r in results if r[0]]
    failures = [r for r in results if not r[0]]
    
    logger.info(f"Success: {len(successes)}, Skipped/Failed: {len(failures)}")

    # 4. Write CSV to /tmp (Lambda's only writable disk space)
    filename = f"ConfigRule_{datetime.date.today().strftime('%Y-%m-%d')}.csv"
    local_path = f"/tmp/{filename}"
    
    headers = [
        'ConfigRule', 'Active', 'Classification', 'ComplianceType', 'AccountAlias',
        'AwsRegion', 'ResourceType', 'ResourceIdentifier', 'Description', 'Annotation',
        'EvaluationTimestamp', 'EvaluationTriggerType', 'AccountId', 'OU',
        'Tag:Name', 'Tag:Application', 'Tag:Owner', 'Tag:Environment'
    ]
    
    # (Simplified CSV writing logic for brevity - paste your actual writing logic here)
    with open(local_path, 'w', encoding='utf-8') as f:
        f.write(','.join(headers) + '\n')
        for account in successes:
            for rule in account.config_rules:
                 # ... Add your existing CSV row formatting here ...
                 f.write(f"{rule}\n") # Assuming __str__ handles the formatting

    # 5. Upload to S3
    s3 = boto3.client('s3')
    s3_key = f"reports/{filename}"
    s3.upload_file(local_path, S3_BUCKET, s3_key)
    logger.info(f"Report uploaded to s3://{S3_BUCKET}/{s3_key}")
    
    return {"status": "success", "s3_key": s3_key}