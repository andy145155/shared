import logging
import subprocess
import time
import shlex
import json

# Create a logger for this module
logger = logging.getLogger(__name__)

class IstioMTLSVerifier:
    def __init__(self, namespace, target_svc, source_sidecar, source_no_sidecar):
        """
        Initialize the Verifier with environment details.
        
        :param namespace: The K8s namespace where tests run.
        :param target_svc: The name of the service we are trying to reach.
        :param source_sidecar: The pod name that HAS a sidecar.
        :param source_no_sidecar: The pod name that DOES NOT have a sidecar.
        """
        self.ns = namespace
        self.target_svc = target_svc
        self.source_sidecar = source_sidecar
        self.source_no_sidecar = source_no_sidecar
        
        # Construct the internal cluster URL
        self.target_url = f"http://{self.target_svc}.{self.ns}.svc.cluster.local:80/v1/template/ping"

    def _run_command(self, command, check=True):
        """Internal helper to run shell commands."""
        try:
            args = shlex.split(command)
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=check
            )
            return result
        except subprocess.CalledProcessError as e:
            # We log the stderr here for easier debugging
            logger.debug(f"Command failed: {command}")
            logger.debug(f"Error output: {e.stderr}")
            raise e

    def _check_connection(self, source_pod, expect_success, retries=3, delay=2):
        """
        Runs curl from a source pod to the target.
        Handles retries and positive/negative assertions.
        """
        cmd = (
            f"kubectl exec {source_pod} -n {self.ns} -- "
            f"curl -v --connect-timeout 5 {self.target_url}"
        )

        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Attempt {attempt}/{retries}: Connection from {source_pod}...")
                self._run_command(cmd, check=True)

                # If we are here, curl succeeded (Exit Code 0)
                if expect_success:
                    logger.info("✅ Connection succeeded as expected.")
                    return
                else:
                    raise Exception(f"❌ SECURITY FAIL: Traffic from {source_pod} was ALLOWED (should be blocked).")

            except subprocess.CalledProcessError as e:
                # If we are here, curl failed (Non-Zero Exit Code)
                if not expect_success:
                    logger.info(f"✅ Connection blocked as expected. (Curl exit code: {e.returncode})")
                    return
                else:
                    logger.warning(f"Connection failed (Attempt {attempt}). Error: {e.stderr}")
            
            if attempt < retries:
                time.sleep(delay)

        # Final decision after retries exhausted
        if expect_success:
            raise Exception(f"❌ Connectivity Test FAILED: Could not connect from {source_pod}.")
        
        # If expect_success is False, we technically passed if we never returned inside the loop?
        # No, if we are here and expect_success is False, it means we actually caught an exception every time?
        # Actually, in the negative case:
        #   - If curl succeeds, we raise Exception -> Test Fails.
        #   - If curl fails, we return -> Test Passes.
        # So falling through here is only possible for the Positive case failure.
        pass

    def _verify_envoy_config(self):
        """
        Best Practice: Verifies mTLS is configured in Envoy via localhost:15000
        """
        logger.info(f"🔍 Verifying Envoy mTLS configuration on {self.source_sidecar}...")
        
        cmd = f"kubectl exec {self.source_sidecar} -n {self.ns} -- curl -s -f localhost:15000/config_dump"
        
        try:
            result = self._run_command(cmd, check=True)
            config_dump = json.loads(result.stdout)
            
            target_cluster_name = f"outbound|80||{self.target_svc}.{self.ns}.svc.cluster.local"
            found_mtls = False

            # Parse deep JSON structure
            for config in config_dump.get('configs', []):
                if 'ClustersConfigDump' in config.get('@type', ''):
                    for cluster in config.get('dynamic_active_clusters', []):
                        cluster_detail = cluster.get('cluster', {})
                        if cluster_detail.get('name') == target_cluster_name:
                            transport_socket = cluster_detail.get('transport_socket', {})
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