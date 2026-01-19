from kubernetes import client
from kubernetes.client.rest import ApiException
import logging

logger = logging.getLogger(__name__)

def ensure_namespace(core_api: client.CoreV1Api, namespace_name: str):
    """
    Creates a Namespace if it doesn't exist.
    Idempotent: Returns successfully if the namespace is already there.
    """
    # Define the Namespace object using the Python class
    ns_body = client.V1Namespace(
        metadata=client.V1ObjectMeta(name=namespace_name)
    )

    try:
        core_api.create_namespace(body=ns_body)
        logger.info(f"Created namespace: {namespace_name}")
    except ApiException as e:
        if e.status == 409: # HTTP 409: Conflict (Already Exists)
            logger.info(f"Namespace '{namespace_name}' already exists. Proceeding.")
        else:
            # Re-raise unexpected errors (e.g., Auth failure, Network issue)
            logger.error(f"Failed to create namespace {namespace_name}: {e}")
            raise



            # lib/utils.py

def ensure_clean_state(route53_client, zone_id, record_name: str):
    """
    Pre-condition check: 
    Verifies that the target DNS record does NOT exist.
    If it exists, it forces a cleanup and waits for deletion.
    """
    logger.info(f"Pre-check: Verifying clean slate for {record_name}...")

    # 1. Check if it exists
    if route53.check_dns_record(route53_client, zone_id, record_name):
        logger.warning(f"⚠️ Stale record found for {record_name}. Cleaning it up before testing...")
        
        # 2. Force delete
        route53.cleanup_record(route53_client, zone_id, record_name)
        
        # 3. Wait for it to disappear
        is_gone = route53.wait_for_dns_deletion(
            route53_client, 
            zone_id, 
            record_name, 
            timeout=60 # Shorter timeout for pre-check
        )
        
        if not is_gone:
            raise RuntimeError(
                f"❌ CRITICAL: Cannot clean environment. Record {record_name} is stuck. "
                "Aborting test to prevent false results."
            )
        
        logger.info("✅ Environment cleaned. Proceeding with test.")
    else:
        logger.info("✅ Environment is clean.")