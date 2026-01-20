import logging
from lib import k8s, route53, config

logger = logging.getLogger(__name__)

def run_test_suite(source_name, manifest_path, k8s_clients, route53_client, zone_id, external_mode, test_namespace):
    """
    Runs a single test case.
    Note: We DO NOT delete K8s resources here. 
    They accumulate in the namespace until the namespace itself is deleted at the end.
    """
    source_host_name = f"{source_name}.{config.TEST_BASE_HOSTNAME}"
    
    # 1. Pre-Check (Clean Slate for DNS)
    if route53.check_dns_record(route53_client, zone_id, source_host_name):
        logger.warning(f"Stale record {source_host_name} found. Cleaning...")
        route53.cleanup_record(route53_client, zone_id, source_host_name)
        route53.wait_for_dns_deletion(route53_client, zone_id, source_host_name)

    # 2. Deploy Resources (Fire and Forget)
    test_ctx = {
        "TEST_NAMESPACE": test_namespace,
        "TEST_HOSTNAME": source_host_name
    }
    
    # Just create them. No context manager needed here.
    k8s.deploy_resources(k8s_clients, manifest_path, test_ctx)

    # 3. Verify DNS Creation
    logger.info(f"Waiting for DNS propagation: {source_host_name}")
    if not route53.wait_for_dns_propagation(route53_client, zone_id, source_host_name):
        raise RuntimeError(f"DNS Propagation timed out for {source_name}")
        
    # 4. Verify Auto-Deletion (Optional Logic)
    # If we want to verify that deleting the Ingress deletes the DNS, 
    # we would need to manually delete the resource here. 
    # BUT, if you just want to test "Can I create records?", you can skip this.
    
    # If you DO want to test deletion behavior, you must manually delete the specific resource here:
    if external_mode == "sync":
         # ... find and delete the specific ingress/service ...
         # ... wait for dns deletion ...
         pass

    # 5. Final DNS Cleanup (To save money/clutter)
    # Even though K8s resources die with the namespace, Route53 records might stay 
    # if ExternalDNS doesn't clean them fast enough before the Pod dies.
    # It's good practice to ensure Route53 is clean.
    route53.cleanup_record(route53_client, zone_id, source_host_name)
    
    logger.info(f"--- TEST PASSED: {source_name} ---")