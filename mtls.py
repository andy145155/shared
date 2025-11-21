import logging
import sys
import subprocess
import time
import json
import shlex
from string import Template

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants (Can be moved to config fileimport logging
import sys
import os
import time
import uuid
import subprocess
import shlex
import socket
import ssl
import datetime
from string import Template
from kubernetes import client, config

# ==========================================
# 1. CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt="%H:%M:%S"
)

# Env Vars
TEST_NAMESPACE = os.getenv("TEST_NAMESPACE", "test-automation-ns")
TARGET_APP_NAME = os.getenv("TARGET_APP_NAME", "test-app")
GATEWAY_NAME = os.getenv("GATEWAY_NAME", "test-automation-gateway")
ISTIO_NAMESPACE = os.getenv("ISTIO_NAMESPACE", "istio-system")
INGRESS_SVC_NAME = os.getenv("INGRESS_SVC_NAME", "istio-ingressgateway")

# ==========================================
# 2. INFRASTRUCTURE LAYER (Read)
# ==========================================
class K8sClient:
    """
    Handles reading state from the cluster using the K8s Python Lib.
    """
    def __init__(self):
        try:
            config.load_kube_config()
        except config.ConfigException:
            config.load_incluster_config()
        self.v1 = client.CoreV1Api()

    def get_ingress_info(self, timeout=60):
        """
        Returns:
          1. External Hostname (for health check only)
          2. Internal ClusterIP (for actual testing to bypass Hairpin NAT)
        """
        logging.info(f"🔍 Fetching Ingress Info for {INGRESS_SVC_NAME}...")
        
        start = time.time()
        while time.time() - start < timeout:
            try:
                svc = self.v1.read_namespaced_service(INGRESS_SVC_NAME, ISTIO_NAMESPACE)
                
                # 1. Get ClusterIP (The "Back Door" for testing)
                cluster_ip = svc.spec.cluster_ip

                # 2. Get LoadBalancer (The Health Check)
                # We check this just to ensure the Cloud Infra is provisioned,
                # even though we won't route traffic through it to avoid Hairpin NAT.
                if svc.status.load_balancer.ingress:
                    lb_host = svc.status.load_balancer.ingress[0].hostname
                    logging.info(f"✅ Infra Ready. LB: {lb_host}, ClusterIP: {cluster_ip}")
                    return lb_host, cluster_ip
                
                logging.info("⏳ Waiting for AWS/Cloud LoadBalancer assignment...")
            except Exception as e:
                logging.warning(f"API Error: {e}")
            
            time.sleep(5)
        
        raise TimeoutError("Ingress LoadBalancer was not provisioned in time.")

# ==========================================
# 3. ACTION LAYER (Write)
# ==========================================
def run_command(cmd, stdin=None):
    try:
        res = subprocess.run(
            shlex.split(cmd), 
            input=stdin, 
            capture_output=True, 
            text=True, 
            check=True
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Command Failed: {cmd}\nSTDERR: {e.stderr}")
        raise

def apply_yaml_template(path, **vars):
    """
    Renders YAML with $VARS and applies via kubectl.
    """
    logging.info(f"📄 Applying Template: {path}")
    with open(path) as f:
        rendered = Template(f.read()).substitute(vars)
    
    run_command("kubectl apply -f -", stdin=rendered)

# ==========================================
# 4. VERIFICATION LOGIC (Test)
# ==========================================
def verify_tls_cert(hostname, connect_ip):
    """
    Layer 4/5 Check: Connects via IP, sends SNI=hostname, checks Cert Validity.
    """
    logging.info(f"🔒 Verifying TLS Certificate for {hostname}...")
    context = ssl.create_default_context()
    
    # NOTE: If using internal CA not in container, uncomment:
    # context.check_hostname = False
    # context.verify_mode = ssl.CERT_NONE

    try:
        sock = socket.create_connection((connect_ip, 443), timeout=5)
        with context.wrap_socket(sock, server_hostname=hostname) as ssock:
            cert = ssock.getpeercert()
            not_after = datetime.datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
            
            if not_after < datetime.datetime.utcnow():
                logging.error(f"❌ Cert EXPIRED on {not_after}")
                return False
            
            logging.info(f"✅ TLS Valid. Expires: {not_after}")
            return True
    except Exception as e:
        logging.error(f"❌ TLS Handshake Failed: {e}")
        return False

def verify_connectivity(url, sni_host, connect_ip, expect="200", retries=10):
    """
    Layer 7 Check: Uses --resolve to map SNI_HOST -> CONNECT_IP.
    This bypasses DNS and Hairpin NAT.
    """
    logging.info(f"🌍 Checking Traffic: {url} -> {connect_ip} (Expect {expect})")
    
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--resolve {sni_host}:443:{connect_ip} "
        f"{url}"
    )

    for i in range(1, retries + 1):
        try:
            code = run_command(curl_cmd)
            if code == expect:
                logging.info(f"✅ Success! Got HTTP {code}.")
                return True
            logging.info(f"   Attempt {i}: Got {code}, waiting...")
        except Exception:
            pass
        time.sleep(2)

    logging.error(f"❌ Traffic Test Failed. Expected {expect}, never got it.")
    return False

# ==========================================
# 5. MAIN ORCHESTRATION
# ==========================================
def main():
    logging.info("🚀 STARTING INGRESS VERIFICATION")
    
    try:
        # 1. READ: Get Infrastructure Details
        k8s = K8sClient()
        # We get the ClusterIP to Short-Circuit the network path
        _, internal_ip = k8s.get_ingress_info()

        # 2. PREPARE: Generate Unique Test Identity
        # This ensures isolation. No collisions with other CI jobs.
        run_id = str(uuid.uuid4())[:8]
        fake_host = f"verify-{run_id}.example.com"
        logging.info(f"🧪 Generated Test Host: {fake_host}")

        # 3. WRITE: Apply Config
        # We bind the Gateway to our unique Fake Host
        apply_yaml_template(
            "templates/ingress.yaml",
            TEST_GATEWAY_NAME=GATEWAY_NAME,
            TEST_NAMESPACE=TEST_NAMESPACE,
            TARGET_APP_NAME=TARGET_APP_NAME,
            INGRESS_HOST=fake_host 
        )

        # 4. TEST A: TLS Integrity
        # Check if Istio loaded a valid cert for our SNI
        if not verify_tls_cert(fake_host, internal_ip):
            raise Exception("TLS Certificate Check Failed")

        # 5. TEST B: Positive Connectivity (The Happy Path)
        # "Can I reach the app via the fake host?"
        target_url = f"https://{fake_host}/v1/template/ping"
        if not verify_connectivity(target_url, fake_host, internal_ip, expect="200"):
            raise Exception("Positive Traffic Check Failed")

        # 6. TEST C: Security Isolation (The Negative Path)
        # "If I use a DIFFERENT host, do I get blocked?"
        # This proves we didn't accidentally deploy a wildcard '*' gateway.
        evil_host = "evil.example.com"
        evil_url = f"https://{evil_host}/v1/template/ping"
        logging.info("🛡️ Running Security Isolation Test...")
        
        if not verify_connectivity(evil_url, evil_host, internal_ip, expect="404", retries=2):
            raise Exception("Security Isolation Failed! Gateway accepted invalid host.")

        logging.info("🎉 ALL TESTS PASSED SUCCESSFULLY")
        sys.exit(0)

    except Exception as e:
        logging.error(f"💥 FATAL ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main())
ISTIO_NAMESPACE = "istio-system"
INGRESS_SVC_NAME = "istio-ingressgateway"
TEST_NAMESPACE = "test-automation-ns"
TEST_GATEWAY_NAME = "test-gateway"
TARGET_APP_NAME = "test-app" # Assumes this app is already deployed

# --- Helper Functions ---

def run_command(command, check=True, timeout=30, stdin_data=None):
    """
    Executes a shell command and returns stdout/stderr.
    Handles stdin for piping YAML directly to kubectl.
    """
    try:
        result = subprocess.run(
            shlex.split(command),
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=stdin_data
        )
        return result.stdout.strip(), result.stderr.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {command}")
        if e.stderr: logging.error(f"STDERR: {e.stderr}")
        if check: raise
        return e.stdout, e.stderr
    except Exception as e:
        logging.error(f"Execution error: {e}")
        if check: raise
        return "", str(e)

def get_ingress_info_cli(namespace, service_name, timeout=60):
    """
    Fetches External Hostname and Internal ClusterIP using kubectl JSON output.
    Retries until the LoadBalancer hostname is assigned by the Cloud Provider.
    """
    logging.info(f"🔍 Querying {service_name} in {namespace} (CLI JSON mode)...")
    
    cmd = f"kubectl get svc {service_name} -n {namespace} -o json"
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            stdout, _ = run_command(cmd, check=False)
            if not stdout:
                time.sleep(2)
                continue

            # Parse JSON (Safer than text parsing)
            svc_data = json.loads(stdout)
            
            # 1. Get ClusterIP
            cluster_ip = svc_data.get('spec', {}).get('clusterIP')

            # 2. Get Hostname
            status = svc_data.get('status', {}).get('loadBalancer', {}).get('ingress', [])
            
            if status and 'hostname' in status[0]:
                hostname = status[0]['hostname']
                logging.info(f"✅ Found Infrastructure - Host: {hostname}, IP: {cluster_ip}")
                return hostname, cluster_ip
            
            logging.info("Waiting for Cloud LoadBalancer assignment...")
            
        except json.JSONDecodeError:
            logging.warning("Failed to parse kubectl output.")
        except Exception as e:
            logging.warning(f"Retry: {e}")

        time.sleep(5)

    raise Exception(f"Timed out waiting for {service_name} LoadBalancer.")

def apply_yaml_template(template_path, **vars):
    """
    Reads YAML, substitutes $VARs, and applies via kubectl stdin.
    Atomic: No temp files created.
    """
    logging.info(f"📄 Rendering and Applying {template_path}...")
    
    try:
        with open(template_path, "r") as f:
            content = f.read()
        
        # Substitute variables
        rendered_yaml = Template(content).substitute(vars)
        
        # Apply directly via pipe
        run_command("kubectl apply -f -", stdin_data=rendered_yaml)
        logging.info("Gateway resources applied successfully.")
        
    except KeyError as e:
        logging.error(f"Template Error: Missing variable ${e.args[0]}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Failed to apply YAML: {e}")
        sys.exit(1)

def verify_connectivity(ingress_host, cluster_ip):
    """
    Verifies ingress flow using curl --resolve.
    Maps the External Hostname to the Internal ClusterIP to bypass Hairpin NAT.
    """
    target_url = f"https://{ingress_host}/v1/template/ping"
    
    # --resolve forces curl to send the correct SNI/Host header but connect to the internal IP
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--resolve {ingress_host}:443:{cluster_ip} "
        f"{target_url}"
    )

    logging.info(f"🌍 Starting Connectivity Check: {target_url}")
    logging.info(f"Resolution override: {ingress_host} -> {cluster_ip}")

    # Polling Loop (Replaces time.sleep(15))
    for attempt in range(1, 11):
        stdout, _ = run_command(curl_cmd, check=False)
        status_code = stdout.strip()

        if status_code == "200":
            logging.info(f"✅ SUCCESS: Endpoint returned 200 OK on attempt {attempt}")
            return True
        
        logging.warning(f"Attempt {attempt}: Got status '{status_code}'. Retrying in 3s...")
        time.sleep(3)

    logging.error("❌ Connectivity check failed after all retries.")
    return False

# --- Main Execution ---

def check_ingress_gateway():
    logging.info("--- 5. Checking Ingress Gateway (Best Practice) ---")

    try:
        # STEP 1: Get Infrastructure Info FIRST
        # We do this before applying YAML so we can inject the hostname directly.
        real_ingress_host, internal_ip = get_ingress_info_cli(
            ISTIO_NAMESPACE, INGRESS_SVC_NAME
        )

        # STEP 2: Apply Fully Configured YAML
        # No patching required. The Gateway is created correctly from the start.
        apply_yaml_template(
            "ingress.yaml",
            TEST_GATEWAY_NAME=TEST_GATEWAY_NAME,
            TEST_NAMESPACE=TEST_NAMESPACE,
            INGRESS_HOST=real_ingress_host,
            TARGET_APP_NAME=TARGET_APP_NAME
        )

        # STEP 3: Verify Connectivity
        # We poll immediately. Istio is usually fast.
        success = verify_connectivity(real_ingress_host, internal_ip)
        
        if not success:
            logging.error("Ingress Gateway Verification FAILED.")
            sys.exit(1)
            
        logging.info("🎉 Ingress Gateway Verification PASSED.")

    except Exception as e:
        logging.error(f"Fatal Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_ingress_gateway()