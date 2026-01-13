# main.py
import sys
import time
import logging
import signal
from lib import k8s, external_dns # (Assuming you moved detection here)
from lib.k8s import initialize_k8s_clients, apply_resource, k8s_resource_manager

# ... imports ...

# 1. DEFINE THE MAP
# keys match the 'source' strings from ExternalDNS args (service, ingress, gateway-httproute)
SOURCE_TEST_MAP = {
    "service": "manifests/service.yaml",
    "ingress": "manifests/ingress.yaml",
    "istio-gateway": "manifests/gateway.yaml", # or "gateway-httproute" depending on what external-dns reports
}

def run_test_suite(source_name, manifest_path, core, apps, custom, route53, zone_id):
    """
    Helper function to run the full cycle for ONE source.
    """
    logger.info(f"\n🔹 STARTING TEST FOR SOURCE: {source_name}")
    
    # Pass the specific manifest_path to the manager
    with k8s_resource_manager(core, apps, custom, manifest_path, TEST_NAMESPACE) as resources:
        
        # Deploy
        for res in resources:
            apply_resource(core, apps, custom, res, TEST_NAMESPACE)

        # Verify
        # Note: Ideally, each manifest uses a unique hostname to avoid caching collisions
        # e.g. service-test.example.com vs ingress-test.example.com
        if not wait_for_dns_propagation(route53, zone_id, TEST_HOSTNAME):
             raise RuntimeError(f"DNS Propagation Failed for {source_name}")
             
        # Optional: Sync mode check logic can go here (omitted for brevity)
    
    logger.info(f"✅ SOURCE {source_name} PASSED\n")


def main():
    signal.signal(signal.SIGTERM, handle_sigterm)
    exit_code = 0
    
    try:
        # 1. Clients
        core_api, apps_api, custom_api = initialize_k8s_clients()
        route53_client = get_route53_client()

        # 2. Detect Configuration (Get list of sources)
        # Ensure your detect function returns a list, e.g. ['service', 'ingress']
        config = detect_external_dns_config(core_api) 
        
        logger.info(f"ExternalDNS Version: {config.version}")
        logger.info(f"Enabled Sources: {config.sources}")

        # 3. Find Zone
        zone_id = get_hosted_zone_id(route53_client, HOSTED_ZONE_NAME, config.private_zone)

        # 4. Filter Sources to Test
        # We only test sources that are BOTH enabled in the cluster AND defined in our map
        active_sources = [s for s in config.sources if s in SOURCE_TEST_MAP]

        if not active_sources:
            logger.warning("No testable sources detected! (Check SOURCE_TEST_MAP vs Cluster Args)")
            return

        # 5. LOOP THROUGH SOURCES
        for source in active_sources:
            manifest_path = SOURCE_TEST_MAP[source]
            run_test_suite(
                source, 
                manifest_path, 
                core_api, apps_api, custom_api, route53_client, 
                zone_id
            )

        logger.info("🎉 ALL TEST SUITES COMPLETED SUCCESSFULLY")

    except Exception as e:
        logger.exception(f"Critical Failure: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()