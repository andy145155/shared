import logging
import sys
import subprocess
import time
import shlex
from string import Template
from kubernetes import client, config

# --- Configuration ---
LOG_LEVEL = logging.INFO
KUBECTL_TIMEOUT = 30

# Setup Logging
logging.basicConfig(
    level=LOG_LEVEL,
    handlers=[logging.StreamHandler(sys.stdout)],
    format="%(levelname)s: %(asctime)s - %(message)s"
)

# --- K8s Client Setup ---
# Tries to load local kubeconfig first, falls back to in-cluster config
try:
    config.load_kube_config()
except config.ConfigException:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        logging.warning("Could not load K8s config. 'get_ingress_info' will fail.")

v1 = client.CoreV1Api()

# --- Helper Functions ---

def run_command(command, check=True, timeout=KUBECTL_TIMEOUT, stdin_data=None):
    """
    Executes a shell command. 
    Used primarily for 'kubectl apply' where the K8s python lib is too verbose.
    """
    logging.info(f"Running command: {command}")
    
    try:
        result = subprocess.run(
            shlex.split(command),
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=stdin_data
        )
        
        stdout_str = result.stdout.strip() if result.stdout else ""
        stderr_str = result.stderr.strip() if result.stderr else ""

        if stdout_str:
            logging.info(f"STDOUT:\n{stdout_str}")
        if stderr_str:
            # Warning: some kubectl commands print info to stderr even on success
            logging.warning(f"STDERR:\n{stderr_str}")
            
        return stdout_str, stderr_str

    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with exit code {e.returncode}")
        if e.stdout: logging.info(f"STDOUT:\n{e.stdout}")
        if e.stderr: logging.warning(f"STDERR:\n{e.stderr}")
        if check:
            raise
        return e.stdout, e.stderr

    except Exception as e:
        logging.error(f"Unexpected error:\n{e}")
        if check:
            raise
        return "", str(e)

def apply_yaml_template(template_path, is_delete=False, **template_vars):
    """
    Reads a YAML file, substitutes variables using string.Template ($VAR),
    and applies it via kubectl.
    
    NOTE: Requires YAML files to use $VAR or ${VAR} syntax.
    """
    action = "delete" if is_delete else "apply"
    verb = "Deleting" if is_delete else "Applying"

    logging.info(f"{verb} from template: {template_path}")

    try:
        with open(template_path, "r") as f:
            content = f.read()

        # Use string.Template for safe substitution (avoids {{ }} conflicts)
        # substitute() will raise KeyError if a var is missing, which is good for safety.
        src = Template(content)
        yaml_string = src.substitute(template_vars)

        # Pass the rendered YAML directly to kubectl via stdin
        cmd = f"kubectl {action} -f -"
        run_command(cmd, stdin_data=yaml_string)

    except KeyError as e:
        logging.error(f"TEMPLATE ERROR: {template_path} expects variable ${e.args[0]}, but it was not provided.")
        if not is_delete: raise
    except Exception as e:
        logging.error(f"Failed to {action} YAML from {template_path}: {e}")
        if not is_delete: raise

def get_ingress_info(namespace="istio-system", service_name="istio-ingressgateway"):
    """
    Reliably fetches the External Hostname and Internal ClusterIP using the K8s Python Lib.
    This avoids fragile string parsing of kubectl output.
    """
    logging.info(f"Querying Service {service_name} in {namespace} via K8s API...")
    
    try:
        svc = v1.read_namespaced_service(service_name, namespace)
        
        # 1. Get ClusterIP (Safe)
        cluster_ip = svc.spec.cluster_ip
        
        # 2. Get External Hostname (With checks)
        ingress_status = svc.status.load_balancer.ingress
        if not ingress_status:
             raise Exception(f"Service {service_name} has no LoadBalancer Ingress status. Is the Cloud LB provisioned?")
             
        hostname = ingress_status[0].hostname
        
        logging.info(f"Discovered Infrastructure - Host: {hostname}, IP: {cluster_ip}")
        return hostname, cluster_ip

    except Exception as e:
        logging.error(f"K8s API Error: {e}")
        raise

def verify_connectivity(ingress_host, cluster_ip, path="/v1/template/ping"):
    """
    Verifies connectivity using curl with a retry loop.
    Uses --resolve to map the Hostname to the ClusterIP (Grey Box testing).
    """
    target_url = f"https://{ingress_host}{path}"
    
    # Curl command:
    # -k: Allow insecure (self-signed)
    # -s: Silent
    # -o /dev/null: Ignore body
    # -w: Print status code
    # --resolve: Force SNI and DNS resolution to internal IP
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--resolve {ingress_host}:443:{cluster_ip} "
        f"{target_url}"
    )

    logging.info(f"Starting connectivity check: {target_url}")
    logging.info(f"Mapping {ingress_host} -> {cluster_ip}")

    # Retry Logic
    max_retries = 10
    for attempt in range(1, max_retries + 1):
        stdout, _ = run_command(curl_cmd, check=False)
        status_code = stdout.strip()

        if status_code == "200":
            logging.info(f"✅ Success! Endpoint returned 200 OK on attempt {attempt}")
            return True
        
        logging.warning(f"Attempt {attempt}: Got status '{status_code}'. Retrying in 3s...")
        time.sleep(3)

    logging.error("❌ Connectivity check failed after all retries.")
    return False

def verify_ingress_isolation(cluster_ip):
    """
    NEGATIVE TEST: Sends traffic to the Ingress IP using a BOGUS hostname.
    
    Goal: Verify that Istio BLOCKS traffic that doesn't match our VirtualService.
    Expectation: HTTP 404 (Not Found).
    If we get 200 OK, it means our Gateway is too open (security risk).
    """
    fake_host = "unauthorized-user.com"
    path = "/v1/template/ping"
    
    # We map the FAKE host to the REAL ClusterIP
    # This simulates someone pointing their DNS to our LB illegally
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--resolve {fake_host}:443:{cluster_ip} "
        f"https://{fake_host}{path}"
    )

    logging.info(f"🔒 Starting Negative Test (Isolation Check)...")
    logging.info(f"Attempting to access Gateway using bogus host: {fake_host}")

    # We don't need a long retry loop here because we assume the Gateway 
    # is already up (since the Positive Test passed).
    # We just check once or twice.
    
    for attempt in range(1, 4):
        stdout, _ = run_command(curl_cmd, check=False)
        status_code = stdout.strip()

        if status_code == "404":
            logging.info(f"✅ Success! Request was correctly blocked with 404.")
            return True
        elif status_code == "200":
            logging.error(f"❌ SECURITY FAILURE! The Gateway accepted traffic for {fake_host} (Got 200 OK). Check your VirtualService hosts!")
            return False
        else:
            logging.warning(f"Attempt {attempt}: Got status {status_code}. Waiting for 404...")
            time.sleep(2)

    logging.error(f"❌ Isolation Check Failed. Expected 404, got {status_code}.")
    return False

# --- Main Logic ---

def check_ingress_gateway():
    logging.info("--- 5. Checking Ingress Gateway ---")
    
    TEST_NAMESPACE = "test-ns"
    GATEWAY_NAME = "test-gateway"

    # STEP 1: Get Infrastructure Data (The Read)
    # We do this FIRST so we can inject it into the YAML.
    try:
        real_ingress_host, internal_ip = get_ingress_info()
    except Exception:
        logging.error("Stopping test due to infrastructure lookup failure.")
        sys.exit(1)

    # STEP 2: Apply Config (The Write)
    # We inject the hostname immediately. No patching needed.
    apply_yaml_template(
        template_path="ingress.yaml",  # Make sure your YAML uses $INGRESS_HOST
        is_delete=False,
        TEST_GATEWAY_NAME=GATEWAY_NAME,
        TEST_NAMESPACE=TEST_NAMESPACE,
        INGRESS_HOST=real_ingress_host 
    )

    # STEP 3: Verify (The Test)
    # We use the internal IP to bypass Hairpin NAT issues
    success = verify_connectivity(real_ingress_host, internal_ip)
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    check_ingress_gateway()


import ssl
import socket
import datetime

def verify_tls_cert(hostname, connect_ip):
    """
    SSL/TLS VERIFICATION: 
    Connects to the ingress IP while simulating SNI for 'hostname'.
    Verifies:
    1. The handshake succeeds (Cert matches Hostname).
    2. The certificate is not expired.
    3. (Optional) The Issuer is correct.
    """
    context = ssl.create_default_context()
    
    # If using self-signed certs in test, you might need to disable verification:
    # context.check_hostname = False
    # context.verify_mode = ssl.CERT_NONE
    # BUT: For a true verification test, you want defaults (Strict) if possible,
    # or at least verify the dates manually if the CA isn't trusted in the container.

    logging.info(f"🔒 Checking TLS Certificate for {hostname} (via {connect_ip})...")

    try:
        # 1. Create a TCP connection to the specific ClusterIP (Hairpin bypass)
        sock = socket.create_connection((connect_ip, 443), timeout=5)

        # 2. Wrap the socket with SSL, forcing the SNI hostname
        with context.wrap_socket(sock, server_hostname=hostname) as ssock:
            
            # 3. Retrieve the Certificate
            cert = ssock.getpeercert()
            
            # 4. Verify Expiration
            # Ideally, we use the 'notAfter' field.
            # Python returns it as 'Nov 20 12:00:00 2025 GMT'
            not_after_str = cert['notAfter']
            not_after_date = datetime.datetime.strptime(not_after_str, '%b %d %H:%M:%S %Y %Z')
            
            # Simple logic: Must be in the future
            if not_after_date < datetime.datetime.utcnow():
                logging.error(f"❌ CERT EXPIRED! Valid until: {not_after_str}")
                return False
            
            # 5. (Optional) Verify Issuer if you want to be strict
            # issuer = dict(x[0] for x in cert['issuer'])
            # if 'Let\'s Encrypt' not in issuer.get('organizationName', ''):
            #     logging.warning("⚠️ Cert not issued by expected CA")

            logging.info(f"✅ TLS Certificate is valid. Expires: {not_after_str}")
            return True

    except ssl.SSLCertVerificationError as e:
        logging.error(f"❌ TLS Verification Failed: {e}")
        # This usually means the Cert's CN/SAN doesn't match the Hostname
        return False
    except Exception as e:
        logging.error(f"❌ SSL Connection Error: {e}")
        return False
        

def check_ingress_gateway():
    logging.info("--- 5. Checking Ingress Gateway ---")

    # 1. Get Infrastructure
    try:
        real_ingress_host, internal_ip = get_ingress_info()
    except Exception:
        sys.exit(1)

    # 2. Apply Config
    apply_yaml_template(..., INGRESS_HOST=real_ingress_host)

    # 3. TLS Certificate Check (Layer 4/5 Security)
    # Check this FIRST before doing HTTP requests
    logging.info(">>> Running TLS Validity Test...")
    if not verify_tls_cert(real_ingress_host, internal_ip):
        logging.error("TLS Certificate Check Failed.")
        sys.exit(1)

    # 4. Positive Connectivity (Layer 7 Functionality)
    logging.info(">>> Running Positive Connectivity Test...")
    if not verify_connectivity(real_ingress_host, internal_ip):
        sys.exit(1)

    # 5. Negative Isolation (Layer 7 Security)
    logging.info(">>> Running Negative Isolation Test...")
    if not verify_ingress_isolation(internal_ip):
        sys.exit(1)

    logging.info("🎉 All Ingress Checks Passed (TLS + Connectivity + Isolation).")