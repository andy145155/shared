import logging
from lib import k8s, route53, external_dns, utils, config

logger = logging.getLogger(__name__)

def execute_full_verification() -> bool:
    """
    Main Logic:
    1. Detects configuration.
    2. loops through sources (Service, Ingress, etc.).
    3. Creates a fresh namespace for that source -> Tests it -> Deletes the namespace.
    """
    logger.info("Initializing clients...")
    k8s_clients = k8s.initialize_clients()
    route53_client = route53.initialize_client()
    
    try:
        # 1. Discovery
        ext_dns_config = external_dns.get_config(k8s_clients)
        
        active_sources = [
            s for s in ext_dns_config.sources 
            if s in config.SOURCE_MANIFESTS_MAP
        ]
        
        if not active_sources:
            logger.error("No testable sources detected in external-dns config!")
            return False

        failed_sources = []
        
        # 2. Test Loop
        for source in active_sources:
            # Generate a disposable namespace name (e.g., "verification-service")
            # Note: Ensure your external-dns is configured to watch all namespaces or specific labels.
            test_namespace = f"{config.TEST_NAMESPACE}-{source}"
            
            logger.info(f"--- STARTING TEST: {source} (NS: {test_namespace}) ---")

            # THE MAGIC: This Context Manager creates the NS on enter, and deletes it on exit.
            # No matter if the test passes, fails, or crashes, the namespace is removed.
            with k8s.disposable_namespace(k8s_clients, test_namespace):
                try:
                    utils.run_test_suite(
                        source_name=source,
                        manifest_path=config.SOURCE_MANIFESTS_MAP[source],
                        k8s_clients=k8s_clients,
                        route53_client=route53_client,
                        zone_id=route53.get_hosted_zone_id(route53_client, ext_dns_config.private_zone),
                        external_mode=ext_dns_config.mode,
                        test_namespace=test_namespace # Pass the dynamic NS
                    )
                except Exception as e:
                    logger.error(f"Test failed for source '{source}': {e}")
                    failed_sources.append(source)
                    # The 'finally' block in disposable_namespace runs NOW.

        if failed_sources:
            logger.error(f"The following sources failed: {failed_sources}")
            return False
            
        return True

    except Exception:
        logger.exception("Unexpected error during verification logic")
        return False