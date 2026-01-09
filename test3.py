def cleanup_route53_force(route53_client, zone_id, dns_name):
    """
    Forcefully deletes A-Record and prefixed TXT records.
    Uses precise exception handling to avoid masking real permission issues.
    """
    main_target = dns_name if dns_name.endswith(".") else f"{dns_name}."
    txt_target = f"cname-{main_target}"
    
    targets_to_check = [main_target, txt_target]
    changes = []

    logger.info(f"🧹 FORCE CLEANUP: Checking for {targets_to_check}...")

    try:
        # Step 1: Find records (List operations rarely throw exceptions, usually just empty lists)
        for target in targets_to_check:
            try:
                response = route53_client.list_resource_record_sets(
                    HostedZoneId=zone_id, 
                    StartRecordName=target, 
                    MaxItems="1"
                )
                for r in response.get("ResourceRecordSets", []):
                    # Strict Exact Match Check
                    if r["Name"] == target and r["Type"] in ["A", "TXT", "CNAME"]:
                        logger.info(f"   - Found Stale Record: {r['Name']} ({r['Type']})")
                        changes.append({"Action": "DELETE", "ResourceRecordSet": r})
            
            except ClientError as e:
                # Handle specific read errors (like Zone Not Found)
                code = e.response['Error']['Code']
                if code == 'NoSuchHostedZone':
                    logger.error(f"   - Zone {zone_id} does not exist. Skipping cleanup.")
                    return
                elif code == 'AccessDenied':
                    logger.error("   - ❌ ACCESS DENIED: IAM Role cannot list Route53 records.")
                    raise # Re-raise because this is a configuration failure
                else:
                    logger.warning(f"   - Error listing records: {e}")

        # Step 2: Delete records
        if changes:
            logger.info(f"   - Deleting {len(changes)} records...")
            try:
                route53_client.change_resource_record_sets(
                    HostedZoneId=zone_id, 
                    ChangeBatch={"Changes": changes}
                )
                logger.info("   - Route53 Cleaned.")
            
            except ClientError as e:
                code = e.response['Error']['Code']
                # Race Condition: ExternalDNS might have deleted it milliseconds ago
                if code == 'InvalidChangeBatch':
                    logger.info("   - Cleanup skipped: Record was already deleted (Race Condition).")
                else:
                    logger.error(f"   - Failed to delete records: {e}")
        else:
            logger.info("   - No stale records found.")

    except Exception as e:
        # We still keep a generic catch-all at the very top level just to prevent 
        # the cleanup routine from crashing the whole script, but we log it as a bug.
        logger.error(f"   - Unexpected error during Route53 cleanup: {e}")