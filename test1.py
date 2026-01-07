import os
import time
import logging
import yaml
import boto3
from string import Template
from pathlib import Path
from typing import Dict, Tuple, Any, List, Optional, Set

from kubernetes import client, config
from botocore.exceptions import ClientError, BotoCoreError

# --- Configuration ---
AWS_REGION = os.getenv("AWS_REGION", "ap-east-1")
HOSTED_ZONE_NAME = os.getenv("HOSTED_ZONE_NAME", "dmz.ap-east-1.dev-mox.com.")

# Paths to your templates
SERVICE_MANIFEST_PATH = os.getenv("SERVICE_MANIFEST_PATH", "service-test.yaml")
GATEWAY_MANIFEST_PATH = os.getenv("GATEWAY_MANIFEST_PATH", "gateway-test.yaml")

# ExternalDNS Discovery
EXTERNAL_DNS_NAMESPACE = os.getenv("EXTERNAL_DNS_NAMESPACE", "external-dns")
EXTERNAL_DNS_SELECTOR = os.getenv("EXTERNAL_DNS_SELECTOR", "app.kubernetes.io/name=external-dns")

# Test Params
TEST_NAMESPACE = os.getenv("TEST_NAMESPACE", "verification-external-dns")
TEST_HOSTNAME = os.getenv("TEST_HOSTNAME", "external-dns-test.api.kong.dmz.ap-east-1.dev-mox.com")
POLL_TIMEOUT_SECONDS = int(os.getenv("POLL_TIMEOUT_SECONDS", 300))
POLL_INTERVAL_SECONDS = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Config Class ---
class VerificationConfig:
    def __init__(self, mode: str, sources: Set[str]):
        self.mode = mode        # 'sync' or 'upsert-only'
        self.sources = sources  # e.g., {'service', 'istio-gateway'}

# --- K8s Initialization ---
def initialize_k8s_clients():
    try:
        config.load_kube_config()
    except config.ConfigException:
        config.load_incluster_config()
    # Return Core (Svcs), Apps (Deploys), and Custom (Istio) APIs
    return client.CoreV1Api(), client.AppsV1Api(), client.CustomObjectsApi()

# --- 1. Detect Config from Running Pod ---
def detect_external_dns_config(core_api, namespace, label_selector) -> VerificationConfig:
    logger.info(f"🕵️ Detecting configuration from {namespace}...")
    
    mode = "sync"
    sources = set()

    try:
        pods = core_api.list_namespaced_pod(namespace, label_selector=label_selector)
        if not pods.items:
            logger.warning("   - No external-dns pods found. Defaulting to source=service, mode=sync.")
            return VerificationConfig("sync", {"service"})
        
        pod = pods.items[0]
        # Find external-dns container (or first container)
        container = next((c for c in pod.spec.containers if c.name == "external-dns"), pod.spec.containers[0])
        
        args = container.args or []
        for arg in args:
            if "--policy=upsert-only" in arg:
                mode = "upsert-only"
            if "--source=" in arg:
                source_val = arg.split("=", 1)[1]
                sources.add(source_val)

        logger.info(f"   - Detected Mode: {mode.upper()}")
        logger.info(f"   - Detected Sources: {sources}")
        
        if not sources:
            logger.warning("   - No explicit source args found. Assuming default 'service'.")
            sources.add("service")

        return VerificationConfig(mode, sources)

    except Exception as e:
        logger.error(f"   - Detection failed: {e}. using defaults.")
        return VerificationConfig("sync", {"service"})

# --- 2. Load Correct Template ---
def load_manifests(config: VerificationConfig) -> Tuple[List[Dict], str]:
    # Decision Logic: Prefer Service if available, else Gateway
    if "service" in config.sources:
        target_file = SERVICE_MANIFEST_PATH
        logger.info("👉 Strategy Selected: SERVICE (Standard)")
    elif "istio-gateway" in config.sources:
        target_file = GATEWAY_MANIFEST_PATH
        logger.info("👉 Strategy Selected: ISTIO GATEWAY")
    else:
        target_file = SERVICE_MANIFEST_PATH
        logger.warning(f"⚠️ Unknown sources {config.sources}. Defaulting to Service strategy.")

    path = Path(target_file)
    if not path.exists():
        raise FileNotFoundError(f"Manifest {target_file} not found.")

    with path.open("r") as f:
        template = f.read()

    # Render Env Vars
    context = {"TEST_NAMESPACE": TEST_NAMESPACE, "TEST_HOSTNAME": TEST_HOSTNAME}
    rendered = Template(template).safe_substitute(context)
    
    docs = list(yaml.safe_load_all(rendered))
    return [d for d in docs if d], target_file

# --- 3. CRUD Operations (Supports Istio) ---
def apply_resource(core_api, apps_api, custom_api, resource, namespace):
    kind = resource.get("kind")
    group_version = resource.get("apiVersion", "").split("/")
    metadata = resource.get("metadata", {})
    metadata["namespace"] = namespace # Enforce test namespace
    name = metadata.get("name")

    logger.info(f"Applying {kind}: {name}...")
    try:
        if kind == "Service":
            core_api.create_namespaced_service(namespace, resource)
        elif kind == "Deployment":
            apps_api.create_namespaced_deployment(namespace, resource)
        elif kind == "Gateway":
            # Istio Gateway (networking.istio.io/v1beta1)
            custom_api.create_namespaced_custom_object(
                group=group_version[0], 
                version=group_version[1], 
                namespace=namespace, 
                plural="gateways", 
                body=resource
            )
        logger.info(f"✅ Created {kind}/{name}")

    except client.exceptions.ApiException as e:
        if e.status == 409:
            logger.info(f"   - {kind}/{name} already exists. Proceeding.")
        else:
            raise

def cleanup_k8s_resources(core_api, apps_api, custom_api, resources, namespace):
    logger.info("🧹 Cleaning Kubernetes resources...")
    for res in resources:
        kind = res.get("kind")
        name = res.get("metadata", {}).get("name")
        group_version = res.get("apiVersion", "").split("/")
        
        try:
            if kind == "Service":
                core_api.delete_namespaced_service(name, namespace)
            elif kind == "Deployment":
                apps_api.delete_namespaced_deployment(name, namespace)
            elif kind == "Gateway":
                custom_api.delete_namespaced_custom_object(
                    group=group_version[0], 
                    version=group_version[1], 
                    namespace=namespace, 
                    plural="gateways", 
                    name=name
                )
            logger.info(f"   - Deleted {kind}/{name}")
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.error(f"   - Failed to delete {kind}/{name}: {e}")

# --- 4. Route53 Helpers ---
def check_dns_record(route53_client, zone_id, record_name) -> bool:
    target_dns = record_name if record_name.endswith(".") else f"{record_name}."
    try:
        resp = route53_client.list_resource_record_sets(
            HostedZoneId=zone_id, StartRecordName=target_dns, MaxItems="1"
        )
        recs = resp.get("ResourceRecordSets", [])
        if recs and recs[0]["Name"] == target_dns:
            return True
    except (ClientError, BotoCoreError):
        pass
    return False

def wait_for_dns_propagation(route53_client, zone_id, record_name):
    target_dns = record_name if record_name.endswith(".") else f"{record_name}."
    logger.info(f"⏳ CREATION CHECK: Polling {target_dns}...")
    start = time.time()
    while time.time() - start < POLL_TIMEOUT_SECONDS:
        if check_dns_record(route53_client, zone_id, record_name):
            logger.info(f"✅ Found DNS Record: {target_dns}")
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return False

def wait_for_dns_deletion(route53_client, zone_id, record_name):
    target_dns = record_name if record_name.endswith(".") else f"{record_name}."
    logger.info(f"⏳ DELETION CHECK: Polling until {target_dns} is GONE...")
    start = time.time()
    while time.time() - start < POLL_TIMEOUT_SECONDS:
        if not check_dns_record(route53_client, zone_id, record_name):
            logger.info(f"✅ Record Disappeared: {target_dns}")
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return False

def cleanup_route53_force(route53_client, zone_id, dns_name):
    target_dns = dns_name if dns_name.endswith(".") else f"{dns_name}."
    logger.info(f"🧹 FORCE CLEANUP: Checking for stale records...")
    try:
        resp = route53_client.list_resource_record_sets(
            HostedZoneId=zone_id, StartRecordName=target_dns, MaxItems="1"
        )
        changes = []
        for r in resp.get("ResourceRecordSets", []):
            if r["Name"] == target_dns and r["Type"] in ["A", "TXT", "CNAME"]:
                changes.append({"Action": "DELETE", "ResourceRecordSet": r})
        if changes:
            route53_client.change_resource_record_sets(
                HostedZoneId=zone_id, ChangeBatch={"Changes": changes}
            )
            logger.info("   - Route53 Cleaned.")
    except Exception:
        pass

# --- Main Execution ---
def main():
    exit_code = 0
    try:
        # 1. Clients
        core_api, apps_api, custom_api = initialize_k8s_clients()
        r53 = boto3.client("route53", region_name=AWS_REGION)

        # 2. Detect Configuration
        config = detect_external_dns_config(core_api, EXTERNAL_DNS_NAMESPACE, EXTERNAL_DNS_SELECTOR)
        
        # 3. Load Resources
        resources, loaded_file = load_manifests(config)
        logger.info(f"📄 Loaded {len(resources)} resources from {loaded_file}")

        # 4. Find Zone
        zones = r53.list_hosted_zones_by_name(DNSName=HOSTED_ZONE_NAME)
        zone_id = next((z["Id"].split("/")[-1] for z in zones.get("HostedZones", [])
                        if z["Name"] in [HOSTED_ZONE_NAME, HOSTED_ZONE_NAME + "."]), None)
        if not zone_id: raise ValueError(f"Zone {HOSTED_ZONE_NAME} not found")

        try:
            # 5. Deploy
            for res in resources:
                apply_resource(core_api, apps_api, custom_api, res, TEST_NAMESPACE)

            # 6. Verify Creation
            if not wait_for_dns_propagation(r53, zone_id, TEST_HOSTNAME):
                raise RuntimeError("DNS Propagation Failed")
            
            logger.info("🎉 CREATION SUCCESSFUL")

            # 7. Cleanup K8s to trigger Deletion (if sync mode)
            cleanup_k8s_resources(core_api, apps_api, custom_api, resources, TEST_NAMESPACE)
            
            # 8. Check Deletion (Only if Sync Mode)
            if config.mode == "sync":
                logger.info("🔍 Mode is SYNC: Verifying auto-deletion...")
                if wait_for_dns_deletion(r53, zone_id, TEST_HOSTNAME):
                    logger.info("🎉 FULL LIFECYCLE VERIFIED")
                else:
                    logger.error("❌ DELETION FAILED: Record persisted")
                    exit_code = 1
            else:
                logger.info("🔍 Mode is UPSERT-ONLY: Skipping deletion check.")

        except Exception as e:
            logger.error(f"Runtime Error: {e}")
            exit_code = 1
        finally:
            # 9. Safety Net Cleanup
            time.sleep(5)
            cleanup_route53_force(r53, zone_id, TEST_HOSTNAME)

    except Exception as e:
        logger.critical(f"Fatal Error: {e}")
        exit_code = 1
    
    exit(exit_code)

if __name__ == "__main__":
    main()