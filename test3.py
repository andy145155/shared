def cleanup_route53_force(route53_client, zone_id, dns_name):
    """
    Forcefully deletes:
    1. The A-Record (e.g., test.example.com)
    2. The TXT Owner Record (e.g., cname-test.example.com)
    """
    # Ensure trailing dot for strict AWS matching
    main_target = dns_name if dns_name.endswith(".") else f"{dns_name}."
    
    # 1. Define the targets we need to clean
    # Standard external-dns behavior with --txt-prefix=cname-
    txt_target = f"cname-{main_target}" 
    
    targets_to_check = [main_target, txt_target]
    changes = []

    logger.info(f"🧹 FORCE CLEANUP: Checking for {targets_to_check}...")

    try:
        for target in targets_to_check:
            # We must query separately because 'cname-test' and 'test' are far apart in the list
            response = route53_client.list_resource_record_sets(
                HostedZoneId=zone_id, 
                StartRecordName=target, 
                MaxItems="1"
            )
            
            for r in response.get("ResourceRecordSets", []):
                # Strict Exact Match Check
                if r["Name"] == target:
                    # We accept A, TXT, or CNAME types
                    if r["Type"] in ["A", "TXT", "CNAME"]:
                        logger.info(f"   - Found Garbage: {r['Name']} ({r['Type']})")
                        changes.append({"Action": "DELETE", "ResourceRecordSet": r})

        if changes:
            logger.info(f"   - Deleting {len(changes)} records...")
            route53_client.change_resource_record_sets(
                HostedZoneId=zone_id, 
                ChangeBatch={"Changes": changes}
            )
            logger.info("   - Route53 Cleaned.")
        else:
            logger.info("   - No stale records found.")

    except Exception as e:
        logger.error(f"   - Route53 Cleanup failed: {e}")