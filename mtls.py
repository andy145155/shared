import logging
import time
import json
import subprocess

# --- IMPORT YOUR EXISTING UTILITY ---
# Adjust the import path 'lib.utils' based on your folder structure.
# Based on your screenshot, it looks like 'lib.utils' or '..lib.utils'
try:
    from lib.utils import run_command
except ImportError:
    # Fallback or helpful error if path is slightly different in your hierarchy
    raise ImportError("Could not import run_command from lib.utils. Please check your directory structure.")

logger = logging.getLogger(__name__)

class IstioMTLSVerifier:
    def __init__(self, namespace, target_svc, source_sidecar, source_no_sidecar):
        self.ns = namespace
        self.target_svc = target_svc
        self.source_sidecar = source_sidecar
        self.source_no_sidecar = source_no_sidecar
        
        # The endpoint we are testing against
        self.target_url = f"http://{self.target_svc}.{self.ns}.svc.cluster.local:80/v1/template/ping"

    def _check_connection(self, source_pod, expect_success, retries=3, delay=2):
        """
        Runs curl from a source pod to the target using your existing run_command.
        """
        # We use -v to help debug, but rely on exit code for success/fail
        cmd = (
            f"kubectl exec {source_pod} -n {self.ns} -- "
            f"curl -v --connect-timeout 5 {self.target_url}"
        )

        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Attempt {attempt}/{retries}: Connection from {source_pod}...")
                
                # Call your utility. check=True will raise CalledProcessError on failure.
                run_command(cmd, check=True)

                # CASE 1: Curl Succeeded (No Exception raised)
                if expect_success:
                    logger.info("✅ Connection succeeded as expected.")
                    return
                else:
                    # We expected failure, but it worked -> FAIL
                    raise Exception(f"❌ SECURITY FAIL: Traffic from {source_pod} was ALLOWED (should be blocked).")

            except subprocess.CalledProcessError as e:
                # CASE 2: Curl Failed (Exception raised)
                if not expect_success:
                    logger.info(f"✅ Connection blocked as expected. (Exit Code: {e.returncode})")
                    return
                else:
                    # We expected success, but it failed -> Retry or Fail
                    logger.warning(f"Connection failed (Attempt {attempt}).")
            
            if attempt < retries:
                time.sleep(delay)

        # If we exhaust retries without returning
        if expect_success:
            raise Exception(f"❌ Connectivity Test FAILED: Could not connect from {source_pod}.")
        
        # If expect_success is False, and we are here, it means the loop finished.
        # The loop only finishes if we kept catching CalledProcessError (success for negative test)
        # OR if we raised the "SECURITY FAIL" exception (which bubbles up).
        pass

    def _verify_envoy_config(self):
        """
        Verifies mTLS is configured in Envoy via localhost:15000.
        """
        logger.info(f"🔍 Verifying Envoy mTLS configuration on {self.source_sidecar}...")
        
        # Command to get config dump from Envoy Admin API
        cmd = f"kubectl exec {self.source_sidecar} -n {self.ns} -- curl -s -f localhost:15000/config_dump"
        
        try:
            # run_command returns (stdout, stderr)
            stdout, _ = run_command(cmd, check=True)
            
            config_dump = json.loads(stdout)
            
            target_cluster_name = f"outbound|80||{self.target_svc}.{self.ns}.svc.cluster.local"
            found_mtls = False

            # Deep JSON parsing to find the Transport Socket
            for config in config_dump.get('configs', []):
                # Check type safely (handle different Envoy versions/names)
                if 'ClustersConfigDump' in config.get('@type', ''):
                    for cluster in config.get('dynamic_active_clusters', []):
                        cluster_detail = cluster.get('cluster', {})
                        if cluster_detail.get('name') == target_cluster_name:
                            transport_socket = cluster_detail.get('transport_socket', {})
                            
                            # Look for TLS definition
                            if "tls" in transport_socket.get('name', ''):
                                found_mtls = True
                                logger.info(f"✅ Envoy Config Verified: Transport Socket found for {self.target_svc}")
                            break
            
            if not found_mtls:
                raise Exception(f"❌ Envoy Config FAIL: No TLS transport socket found for {self.target_svc}")

        except Exception as e:
            logger.error(f"Failed to verify Envoy config: {e}")
            raise

    def run_suite(self):
        """Main entry point to run all tests."""
        logger.info("Starting Istio mTLS Verification Suite...")
        
        # 1. Positive Test
        logger.info(f"--- Test 1: Sidecar -> Sidecar ({self.source_sidecar}) ---")
        self._check_connection(self.source_sidecar, expect_success=True)

        # 2. Config Verification (White Box)
        logger.info("--- Test 2: Envoy Configuration Check ---")
        self._verify_envoy_config()

        # 3. Negative Test
        logger.info(f"--- Test 3: No-Sidecar -> Sidecar ({self.source_no_sidecar}) ---")
        self._check_connection(self.source_no_sidecar, expect_success=False)

        logger.info("🎉 All Istio mTLS tests PASSED successfully.")