import logging
from lib import k8s, route53, config

logger = logging.getLogger(__name__)

def run_test_suite(source_name, manifest_path, k8s_clients, route53_client, zone_id, external_mode, test_namespace):
    """
    Runs the verification for a single source inside the provided namespace.
    """
    source_host_name = f"{source_name}.{config.TEST_BASE_HOSTNAME}"
    
    # 1. Clean Slate (Route53 check)
    if route53.check_dns_record(route53_client, zone_id, source_host_name):
        logger.warning(f"Stale record {source_host_name} found. Cleaning...")
        route53.cleanup_record(route53_client, zone_id, source_host_name)
        if not route53.wait_for_dns_deletion(route53_client, zone_id, source_host_name, timeout=60):
            raise RuntimeError(f"Unable to clean environment for {source_host_name}")

    # 2. Deploy (Simple fire-and-forget, handled by namespace cleanup)
    test_ctx = {
        "TEST_NAMESPACE": test_namespace,
        "TEST_HOSTNAME": source_host_name
    }
    
    # Just deploy. If this fails, the 'with' block in runner exits and deletes the NS.
    k8s.deploy_resources(k8s_clients, manifest_path, test_ctx)

    # 3. Verify Creation
    logger.info(f"Waiting for DNS propagation: {source_host_name}")
    if not route53.wait_for_dns_propagation(route53_client, zone_id, source_host_name):
        raise RuntimeError(f"DNS Propagation timed out for {source_name}")
        
    # 4. Verify Deletion (After we delete the resource manually OR rely on cleanup?)
    # NOTE: Since we want to verify "Deletion works", we must simulate deletion inside the test
    # BEFORE we destroy the namespace, OR we rely on namespace deletion to trigger it.
    
    if external_mode == "sync":
        logger.info("Verifying deletion logic...")
        # We manually delete the namespace NOW to trigger external-dns cleanup
        # actually, wait... we are inside the 'disposable_namespace' context.
        # If we want to verify external-dns deletes the record, we should delete the resources manually first.
        
        # Re-using the simplified deploy means we don't have the object handles easily.
        # For a verification script, it is SAFER to manually delete the resources here to prove 
        # that "Deleting a Service removes the DNS record".
        
        # Simulating deletion by deleting all resources in the NS (or the NS itself).
        # Let's delete the resources via delete_collection for simplicity:
        _, core_api = k8s_clients
        # Delete all Services in this NS
        if source_name == "service":
            core_api.delete_collection_namespaced_service(test_namespace)
        
        # Verify it disappears from Route53
        if not route53.wait_for_dns_deletion(route53_client, zone_id, source_host_name):
            raise RuntimeError(f"DNS Deletion verification failed for {source_name}")

    # 5. Final Cleanup in Route53 (Just in case external-dns failed)
    route53.cleanup_record(route53_client, zone_id, source_host_name)