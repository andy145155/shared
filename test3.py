import logging
import time
from kubernetes import client, config

class K8sClient:
    """
    A wrapper around the official Kubernetes Python Client.
    Responsible for 'Read' operations (fetching Status, IPs, Secrets).
    """

    def __init__(self):
        # 1. Load Configuration
        # Tries local ~/.kube/config first, then falls back to In-Cluster config.
        try:
            config.load_kube_config()
            logging.info("Loaded local kubeconfig.")
        except config.ConfigException:
            try:
                config.load_incluster_config()
                logging.info("Loaded in-cluster config.")
            except config.ConfigException:
                logging.error("Could not load K8s config. Is this running in a Pod?")
                raise

        # 2. Initialize API Clients
        self.v1 = client.CoreV1Api()
        self.app_v1 = client.AppsV1Api()

    def get_ingress_info(self, namespace="istio-system", service_name="istio-ingressgateway", timeout=60):
        """
        Fetches the External Hostname and Internal ClusterIP.
        Includes a retry loop to wait for Cloud LoadBalancer assignment.
        """
        logging.info(f"🔍 Looking up Service {service_name} in {namespace}...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                svc = self.v1.read_namespaced_service(service_name, namespace)
                
                # Get ClusterIP
                cluster_ip = svc.spec.cluster_ip

                # Get Hostname (Handle cases where AWS hasn't assigned it yet)
                if svc.status.load_balancer.ingress:
                    hostname = svc.status.load_balancer.ingress[0].hostname
                    logging.info(f"✅ Found Infrastructure - Host: {hostname}, IP: {cluster_ip}")
                    return hostname, cluster_ip
                
                logging.info("Waiting for LoadBalancer hostname assignment...")
            except Exception as e:
                logging.warning(f"Error querying service: {e}")

            time.sleep(5)

        raise TimeoutError(f"Timed out waiting for {service_name} LoadBalancer hostname.")

    def verify_pod_ready(self, label_selector, namespace, timeout=60):
        """
        Waits until at least one Pod matching the label is 'Ready'.
        """
        logging.info(f"Waiting for Pods ({label_selector}) to be Ready...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            pods = self.v1.list_namespaced_pod(namespace, label_selector=label_selector)
            for pod in pods.items:
                if pod.status.phase == "Running":
                    # Check readiness conditions
                    ready = next((c for c in pod.status.conditions if c.type == 'Ready' and c.status == 'True'), None)
                    if ready:
                        logging.info(f"✅ Pod {pod.metadata.name} is Ready.")
                        return True
            time.sleep(2)
            
        raise TimeoutError(f"No Pods ready for selector {label_selector}")







import logging
import subprocess
import shlex
import sys
import time
import socket
import ssl
import datetime
from string import Template

# --- Shell Execution ---

def run_command(command, check=True, timeout=30, stdin_data=None):
    """
    Executes a shell command. Useful for 'kubectl apply'.
    """
    logging.debug(f"Running: {command}")
    
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
        logging.error(f"Command failed (Exit {e.returncode})")
        if e.stderr: logging.error(f"STDERR: {e.stderr}")
        if check: raise
        return e.stdout, e.stderr

# --- Templating & Applying ---

def apply_yaml_template(template_path, is_delete=False, **vars):
    """
    Reads a YAML file, substitutes $VARIABLES, and runs kubectl apply/delete.
    """
    action = "delete" if is_delete else "apply"
    verb = "Deleting" if is_delete else "Applying"

    logging.info(f"📄 {verb} {template_path}...")

    try:
        with open(template_path, "r") as f:
            content = f.read()

        # Use string.Template ($VAR syntax)
        # safe_substitute allows partial replacement, strict substitute raises error
        rendered_yaml = Template(content).substitute(vars)

        cmd = f"kubectl {action} -f -"
        run_command(cmd, stdin_data=rendered_yaml)
        
    except KeyError as e:
        logging.error(f"❌ Template Error: Missing variable ${e.args[0]} for {template_path}")
        raise
    except Exception as e:
        logging.error(f"❌ Failed to {action} {template_path}: {e}")
        raise

# --- Network Verification ---

def verify_tls_cert(hostname, connect_ip):
    """
    Connects to connect_ip:443 using SNI=hostname. 
    Checks if the certificate is valid and not expired.
    """
    context = ssl.create_default_context()
    # context.check_hostname = False # Uncomment if testing self-signed without CA mounted
    # context.verify_mode = ssl.CERT_NONE # Uncomment if testing self-signed

    logging.info(f"🔒 Verifying TLS for {hostname} (via {connect_ip})...")
    try:
        sock = socket.create_connection((connect_ip, 443), timeout=5)
        with context.wrap_socket(sock, server_hostname=hostname) as ssock:
            cert = ssock.getpeercert()
            not_after = datetime.datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
            
            if not_after < datetime.datetime.utcnow():
                logging.error("❌ Cert Expired!")
                return False
            
            logging.info(f"✅ TLS Valid. Expires: {not_after}")
            return True
    except Exception as e:
        logging.error(f"❌ TLS Check Failed: {e}")
        return False

def verify_connectivity(url, resolve_host, resolve_ip, expect_status="200", retries=10):
    """
    Uses curl with --resolve to bypass DNS/NAT issues.
    Supports retries for eventual consistency.
    """
    logging.info(f"🌍 Checking Connectivity to {url}...")
    
    curl_cmd = (
        f"curl -k -s -o /dev/null -w '%{{http_code}}' "
        f"--resolve {resolve_host}:443:{resolve_ip} "
        f"{url}"
    )

    for attempt in range(1, retries + 1):
        stdout, _ = run_command(curl_cmd, check=False)
        code = stdout.strip()

        if code == expect_status:
            logging.info(f"✅ Success: Got {code}")
            return True
        
        logging.info(f"   Attempt {attempt}: Got {code}, waiting...")
        time.sleep(2)

    logging.error(f"❌ Failed to get {expect_status} from {url}")
    return False