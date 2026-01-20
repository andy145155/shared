# lib/verification_runner.py
import logging
from lib import k8s, route53, external_dns, utils, config

logger = logging.getLogger(__name__)

def execute_full_verification() -> bool:
    """
    Orchestrates the Setup -> Discovery -> Test -> Teardown lifecycle.
    Returns: True if all tests passed, False otherwise.
    """
    # 1. Initialize Clients
    logger.info("Initializing clients...")
    k8s_clients = k8s.initialize_clients()
    route53_client = route53.initialize_client()
    
    # 2. Infrastructure Setup (Namespace, Roles)
    # The Context Manager ensures this is DELETED even if the script crashes.
    with k8s.infrastructure_manager(k8s_clients, config.TEST_NAMESPACE, cleanup=True):
        
        # 3. Discovery (Find what to test)
        # We do this INSIDE the context so if it fails, namespace is still cleaned.
        try:
            ext_dns_config = external_dns.get_config(k8s_clients)
            
            # Filter active sources based on what is enabled in the pod
            active_sources = [
                s for s in ext_dns_config.sources 
                if s in config.SOURCE_MANIFESTS_MAP
            ]
            
            if not active_sources:
                logger.error("No testable sources detected in external-dns config!")
                return False

            # 4. Run Test Suite for each source
            failed_sources = []
            for source in active_sources:
                manifest_path = config.SOURCE_MANIFESTS_MAP[source]
                try:
                    utils.run_test_suite(
                        source_name=source,
                        manifest_path=manifest_path,
                        k8s_clients=k8s_clients,
                        route53_client=route53_client,
                        zone_id=route53.get_hosted_zone_id(route53_client, ext_dns_config.private_zone),
                        external_mode=ext_dns_config.mode
                    )
                except Exception as e:
                    # Log the specific error but continue to the next source
                    logger.error(f"Test failed for source '{source}': {e}")
                    failed_sources.append(source)
            
            if failed_sources:
                logger.error(f"The following sources failed: {failed_sources}")
                return False
                
            return True

        except Exception as e:
            logger.exception("Unexpected error during verification logic")
            return False