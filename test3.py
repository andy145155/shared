# lib/utils.py
import logging
import time
from lib import k8s, route53, config

logger = logging.getLogger(__name__)

def ensure_clean_state(route53_client, zone_id, record_name):
    """Pre-check: Ensure DNS record is GONE before starting."""
    if route53.check_dns_record(route53_client, zone_id, record_name):
        logger.warning(f"⚠️ Stale record {record_name} found. Force cleaning...")
        route53.cleanup_record(route53_client, zone_id, record_name)
        if not route53.wait_for_dns_deletion(route53_client, zone_id, record_name, timeout=60):
            raise RuntimeError(f"Unable to clean environment for {record_name}")

def run_test_suite(source_name, manifest_path, k8s_clients, route53_client, zone_id, external_mode):
    """
    Runs a single test case (e.g., Service).
    1. Pre-check (Clean Slate)
    2. Deploy K8s Resource
    3. Verify DNS Creation
    4. Verify DNS Deletion
    """
    source_host_name = f"{source_name}.{config.TEST_BASE_HOSTNAME}"
    
    logger.info(f"--- STARTING TEST: {source_name} ---")
    
    # 1. Clean Slate
    ensure_clean_state(route53_client, zone_id, source_host_name)

    # 2. Deploy
    test_ctx = {
        "TEST_NAMESPACE": config.TEST_NAMESPACE,
        "TEST_HOSTNAME": source_host_name
    }
    
    with k8s.resource_manager(k8s_clients, manifest_path, test_ctx) as _:
        # 3. Verify Creation
        logger.info(f"Waiting for DNS propagation: {source_host_name}")
        # Note: Ensure wait_for_dns_propagation swallows transient AWS errors!
        if not route53.wait_for_dns_propagation(route53_client, zone_id, source_host_name):
            raise RuntimeError(f"DNS Propagation timed out for {source_name}")
        
    # 4. Verify Deletion (After Context Manager exits)
    if external_mode == "sync":
        logger.info(f"Verifying auto-deletion for {source_host_name}...")
        if not route53.wait_for_dns_deletion(route53_client, zone_id, source_host_name):
            raise RuntimeError(f"DNS Deletion verification failed for {source_name}")
    
    # 5. Final Safety Cleanup (Just in case)
    route53.cleanup_record(route53_client, zone_id, source_host_name)
    logger.info(f"--- TEST PASSED: {source_name} ---")