import logging
from lib import k8s, route53, external_dns, utils, config

logger = logging.getLogger(__name__)

def execute_full_verification() -> bool:
    logger.info("Initializing clients...")
    k8s_clients = k8s.initialize_clients()
    route53_client = route53.initialize_client()
    
    # ---------------------------------------------------------
    # GLOBAL SAFETY NET:
    # All resources created in this block are destroyed when it exits.
    # ---------------------------------------------------------
    with k8s.infrastructure_manager(k8s_clients, config.TEST_NAMESPACE, cleanup=True):
        
        # 1. Discovery (Find what to test)
        try:
            ext_dns_config = external_dns.get_config(k8s_clients)
            active_sources = [s for s in ext_dns_config.sources if s in config.SOURCE_MANIFESTS_MAP]
            
            if not active_sources:
                logger.error("No testable sources detected!")
                return False

            failed_sources = []
            
            # 2. Run All Tests
            for source in active_sources:
                logger.info(f"--- Running Test: {source} ---")
                try:
                    utils.run_test_suite(
                        source_name=source,
                        manifest_path=config.SOURCE_MANIFESTS_MAP[source],
                        k8s_clients=k8s_clients,
                        route53_client=route53_client,
                        zone_id=route53.get_hosted_zone_id(route53_client, ext_dns_config.private_zone),
                        external_mode=ext_dns_config.mode,
                        test_namespace=config.TEST_NAMESPACE # Pass the global NS
                    )
                except Exception as e:
                    logger.error(f"Test failed for source '{source}': {e}")
                    failed_sources.append(source)
            
            # 3. Report Results
            if failed_sources:
                logger.error(f"Failed sources: {failed_sources}")
                return False
                
            return True

        except Exception as e:
            logger.exception("Unexpected error during verification logic")
            return False
    
    # At this point, the 'with' block has exited, and the Namespace is DELETED.