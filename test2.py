# main.py
import sys
import signal
import logging
from lib import k8s, external_dns, route53, test_runner

# --- CONFIGURATION ---
# Map the 'source' string from external-dns args to your local test files
SOURCE_TEST_MAP = {
    "service": "manifests/service.yaml",
    "ingress": "manifests/ingress.yaml",
    "istio-gateway": "manifests/gateway.yaml",
}

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("platform-automation.main")

def handle_sigterm(signum, frame):
    logger.warning("Received SIGTERM, exiting...")
    sys.exit(1)

def main():
    signal.signal(signal.SIGTERM, handle_sigterm)
    
    try:
        # 1. SETUP CLIENTS (Fail Fast)
        logger.info("Initializing clients...")
        # Unpack the tuple directly or just pass it around
        k8s_clients = k8s.initialize_k8s_clients() 
        # (core, apps, net, custom) = k8s_clients
        
        r53_client = route53.get_client()

        # 2. DISCOVERY
        # We use the CoreV1Api (index 0 of clients) to check the running pod
        config = external_dns.detect_config(k8s_clients[0])
        
        logger.info(f"Detected Config :: Version: {config.version} | Policy: {config.policy}")
        logger.info(f"Enabled Sources: {config.enabled_sources}")
        logger.info(f"Target Zone ID: {config.zone_id}")

        # 3. FILTER SOURCES
        # Compare what the cluster supports vs what tests we have defined
        active_sources = [s for s in config.enabled_sources if s in SOURCE_TEST_MAP]

        if not active_sources:
            logger.error("❌ No testable sources found! (Check SOURCE_TEST_MAP vs Cluster Args)")
            sys.exit(0) # or 1 depending on if this is considered a failure

        # 4. EXECUTION LOOP
        failed_sources = []
        
        for source in active_sources:
            manifest_path = SOURCE_TEST_MAP[source]
            
            try:
                # Delegate the entire lifecycle to the runner
                test_runner.run_test_suite(
                    source_name=source,
                    manifest_path=manifest_path,
                    clients=k8s_clients,
                    route53_client=r53_client,
                    config=config
                )
            except Exception as e:
                logger.error(f"❌ Source '{source}' FAILED: {e}")
                failed_sources.append(source)
                # We continue the loop to test other sources even if one fails

        # 5. FINAL REPORT
        if failed_sources:
            logger.error(f"Test Suite Failed. The following sources had errors: {failed_sources}")
            sys.exit(1)
        else:
            logger.info("🎉 ALL TESTS PASSED SUCCESSFULLY")

    except Exception as e:
        # Catch-all for setup errors (Auth, Network, etc)
        logger.exception("CRITICAL ERROR: Script execution crashed")
        sys.exit(1)

if __name__ == "__main__":
    main()