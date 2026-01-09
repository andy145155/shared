def get_hosted_zone_id(route53_client, hosted_zone_name, private_zone=False):
    """
    Finds the Zone ID using list_hosted_zones (iterating client-side).
    Compatible with restricted IAM policies that deny ListHostedZonesByName.
    """
    # Normalize to ensure trailing dot (AWS standard)
    target_name = hosted_zone_name if hosted_zone_name.endswith(".") else f"{hosted_zone_name}."
    
    logger.info(f"🔍 Searching for Zone ID: {target_name} (Private={private_zone})...")
    
    try:
        # Use Paginator to handle accounts with many zones automatically
        paginator = route53_client.get_paginator('list_hosted_zones')
        
        for page in paginator.paginate():
            for z in page['HostedZones']:
                # 1. Check Exact Name Match
                if z["Name"] == target_name:
                    # 2. Check Private/Public Match (Critical for Split-Horizon)
                    if z["Config"]["PrivateZone"] == private_zone:
                        zone_id = z["Id"].split("/")[-1]
                        logger.info(f"   - ✅ Found Zone ID: {zone_id}")
                        return zone_id
                        
    except (ClientError, BotoCoreError) as e:
        logger.error(f"   - AWS API Error: {e}")
        raise

    type_str = "Private" if private_zone else "Public"
    raise ValueError(f"{type_str} Zone '{hosted_zone_name}' not found in this account.")