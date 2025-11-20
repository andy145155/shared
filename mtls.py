import logging
import time
import json
import subprocess

# 1. Import your Configuration
import config  

# 2. Import your Utility
try:
    from lib.utils import run_command
except ImportError:
    raise ImportError("Could not import 'run_command' from 'lib.utils'")

logger = logging.getLogger(__name__)

# --- Helper Functions ---

def check_connection(source_pod, expect_success, retries=3, delay=2):
    """
    Checks connectivity from source_pod to the global TARGET_URL.
    No need to pass namespace or url; we get them from config.
    """
    # Use variables from config directly
    cmd = (
        f"kubectl exec {source_pod} -n {config.TEST_NAMESPACE} -- "
        f"curl -v --connect-timeout 5 {config.TARGET_URL}"
    )

    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Attempt {attempt}/{retries}: Connection from {source_pod}...")
            
            run_command(cmd, check=True)

            if expect_success:
                logger.info("✅ Connection succeeded as expected.")
                return
            else:
                raise Exception(f"❌ SECURITY FAIL: Traffic from {source_pod} was ALLOWED.")

        except subprocess.CalledProcessError as e:
            if not expect_success:
                logger.info(f"✅ Connection blocked as expected. (Code: {e.returncode})")
                return
            else:
                logger.warning(f"Connection failed (Attempt {attempt}).")
        
        if attempt < retries:
            time.sleep(delay)

    if expect_success:
        raise Exception(f"❌ Connectivity Test FAILED: Could not connect from {source_pod}.")

def verify_envoy_config():
    """
    Verifies Envoy config on the sidecar pod defined in config.
    """
    source_pod = config.CLIENT_SIDECAR_NAME
    target_svc = config.TARGET_APP_NAME
    namespace = config.TEST_NAMESPACE

    logger.info(f"🔍 Verifying Envoy mTLS configuration on {source_pod}...")
    
    cmd = f"kubectl exec {source_pod} -n {namespace} -- curl -s -f localhost:15000/config_dump"
    
    try:
        stdout, _ = run_command(cmd, check=True)
        config_dump = json.loads(stdout)
        
        target_cluster_name = f"outbound|80||{target_svc}.{namespace}.svc.cluster.local"
        found_mtls = False

        for cfg in config_dump.get('configs', []):
            if 'ClustersConfigDump' in cfg.get('@type', ''):
                for cluster in cfg.get('dynamic_active_clusters', []):
                    if cluster.get('cluster', {}).get('name') == target_cluster_name:
                        socket = cluster.get('cluster', {}).get('transport_socket', {})
                        if "tls" in socket.get('name', ''):
                            found_mtls = True
                            logger.info(f"✅ Envoy Config Verified for {target_svc}")
                        break
        
        if not found_mtls:
            raise Exception(f"❌ Envoy Config FAIL: No TLS found for {target_svc}")

    except Exception as e:
        logger.error(f"Failed to verify Envoy config: {e}")
        raise

# --- Main Entry Point ---

def run_istio_mtls_tests():
    """
    No arguments needed! It just runs the suite based on config.py.
    """
    logger.info("Starting Istio mTLS Verification Suite...")
    
    logger.info(f"--- Test 1: Sidecar -> Sidecar ({config.CLIENT_SIDECAR_NAME}) ---")
    check_connection(config.CLIENT_SIDECAR_NAME, expect_success=True)

    logger.info("--- Test 2: Envoy Configuration Check ---")
    verify_envoy_config()

    logger.info(f"--- Test 3: No-Sidecar -> Sidecar ({config.CLIENT_NO_SIDECAR_NAME}) ---")
    check_connection(config.CLIENT_NO_SIDECAR_NAME, expect_success=False)

    logger.info("🎉 All Istio mTLS tests PASSED successfully.")