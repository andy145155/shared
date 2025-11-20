import logging
import sys
import os

# Import our shared tools
from lib.k8s_client import K8sClient
from lib.utils import apply_yaml_template, verify_tls_cert, verify_connectivity

# --- Test Configuration ---
TEST_NAMESPACE = "test-automation-ns"
APP_NAME = "test-app"
GATEWAY_NAME = "test-gateway"
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), '../templates')

def run_suite():
    """
    Main execution flow for Ingress Verification.
    """
    logging.info("🚀 STARTING SUITE: Istio Ingress Verification")

    # 1. Initialize Infrastructure Client
    # We use the Class to handle the "Boring" K8s API stuff
    k8s = K8sClient()

    # 2. Deploy the Target Application (Backend)
    # We ensure the namespace and app exist before trying to route traffic to them
    logging.info("--- Step 1: Deploying Backend Application ---")
    apply_yaml_template(
        f"{TEMPLATE_DIR}/test-app.yaml",
        NAMESPACE=TEST_NAMESPACE,
        APP_NAME=APP_NAME
    )

    # Wait for the backend pod to be ready so we don't get 503s from Envoy
    # (You might need to add this method to K8sClient or just sleep)
    k8s.verify_pod_ready(label_selector=f"app={APP_NAME}", namespace=TEST_NAMESPACE)

    # 3. Get Ingress Infrastructure Details
    # We need the real AWS LoadBalancer Hostname to inject into our Gateway YAML
    logging.info("--- Step 2: Fetching Ingress Infrastructure ---")
    ingress_host, ingress_ip = k8s.get_ingress_info(
        namespace="istio-system", 
        service_name="istio-ingressgateway"
    )

    # 4. Apply Gateway & VirtualService Configuration
    # We inject the real hostname ($INGRESS_HOST) into the template
    logging.info("--- Step 3: Applying Istio Gateway Config ---")
    apply_yaml_template(
        f"{TEMPLATE_DIR}/ingress.yaml",
        NAMESPACE=TEST_NAMESPACE,
        GATEWAY_NAME=GATEWAY_NAME,
        INGRESS_HOST=ingress_host,
        TARGET_APP=APP_NAME
    )

    # 5. Run Verification Tests
    logging.info("--- Step 4: Running Verifications ---")

    # TEST A: TLS Certificate Check (Layer 4/5)
    if not verify_tls_cert(ingress_host, ingress_ip):
        logging.error("❌ TLS Certificate verification failed.")
        raise Exception("TLS Failure")

    # TEST B: Positive Connectivity Check (Layer 7)
    # "Can I reach /ping and get 200 OK?"
    target_url = f"https://{ingress_host}/v1/template/ping"
    if not verify_connectivity(
        url=target_url, 
        resolve_host=ingress_host, 
        resolve_ip=ingress_ip, 
        expect_status="200"
    ):
        logging.error("❌ Positive connectivity check failed.")
        raise Exception("Connectivity Failure")

    # TEST C: Negative Isolation Check (Layer 7 Security)
    # "If I use a fake Host header, do I get blocked (404)?"
    fake_host = "unauthorized-domain.com"
    fake_url = f"https://{fake_host}/v1/template/ping"
    
    logging.info("--- Step 5: Running Negative Security Test ---")
    if not verify_connectivity(
        url=fake_url, 
        resolve_host=fake_host, 
        resolve_ip=ingress_ip, 
        expect_status="404", # We EXPECT failure here
        retries=2 # Don't wait long for a negative test
    ):
        logging.error("❌ Security Isolation check failed (Traffic was not blocked).")
        raise Exception("Security Failure")

    logging.info("✅ SUITE PASSED: Istio Ingress Verification")



    import logging
import sys

# Import the test suites we want to run
from tests import test_ingress

# Configure Global Logging
# This format ensures logs look good in Jenkins/GitLab/Argo logs
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

def main():
    """
    Orchestrator for the Release Verification Pipeline.
    """
    logging.info("========================================")
    logging.info("    RELEASE VERIFICATION AUTOMATION     ")
    logging.info("========================================")

    try:
        # --- Run Suite 1: Ingress ---
        test_ingress.run_suite()

        # --- Run Suite 2: Egress (Future) ---
        # test_egress.run_suite()

        # --- Run Suite 3: Control Plane (Future) ---
        # test_control_plane.run_suite()

        logging.info("========================================")
        logging.info("🎉 ALL TESTS PASSED SUCCESSFULLY")
        logging.info("========================================")
        sys.exit(0)

    except Exception as e:
        logging.error("========================================")
        logging.error(f"💥 FATAL ERROR: Test Suite Failed")
        logging.error(f"Reason: {e}")
        logging.error("========================================")
        sys.exit(1)

if __name__ == "__main__":
    main()