import os
import time
import logging
import yaml
import boto3
from string import Template
from pathlib import Path
from typing import Dict, Tuple, Any, List, Optional

from kubernetes import client, config
from botocore.exceptions import ClientError, BotoCoreError

# --- Configuration ---
AWS_REGION = os.getenv("AWS_REGION", "ap-east-1")
HOSTED_ZONE_NAME = os.getenv("HOSTED_ZONE_NAME", "dmz.ap-east-1.dev-mox.com.")
MANIFEST_PATH = os.getenv("MANIFEST_PATH", "service-test.yaml")
POLL_TIMEOUT_SECONDS = int(os.getenv("POLL_TIMEOUT_SECONDS", 300))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", 10))

# --- Target Config ---
# Where is external-dns installed? (To read its config)
EXTERNAL_DNS_NAMESPACE = os.getenv("EXTERNAL_DNS_NAMESPACE", "external-dns")
# Label selector to find the external-dns pod (Standard Helm chart label)
EXTERNAL_DNS_SELECTOR = os.getenv("EXTERNAL_DNS_SELECTOR", "app.kubernetes.io/name=external-dns")

# --- Dynamic Variables for Test Resources ---
TEST_NAMESPACE = os.getenv("TEST_NAMESPACE", "verification-external-dns")
TEST_HOSTNAME = os.getenv("TEST_HOSTNAME", "external-dns-test.api.kong.dmz.ap-east-1.dev-mox.com")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def load_and_render_manifests(file_path: str) -> Tuple[List[Dict[str, Any]], str, str]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest file not found: {file_path}")

    with path.open("r") as f:
        template_content = f.read()

    context = {"TEST_NAMESPACE": TEST_NAMESPACE, "TEST_HOSTNAME": TEST_HOSTNAME}
    rendered_content = Template(template_content).safe_substitute(context)

    try:
        docs = list(yaml.safe_load_all(rendered_content))
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML: {e}")

    resources = [doc for doc in docs if doc]
    return resources, TEST_NAMESPACE, TEST_HOSTNAME

def initialize_k8s_clients():
    try:
        config.load_kube_config()
    except config.ConfigException:
        config.load_incluster_config()
    return client.CoreV1Api(), client.AppsV1Api()

def detect_verification_mode(core_api, namespace, label_selector):
    """
    Inspects the running external-dns Pod to determine if it is in 'sync' or 'upsert-only' mode.
    """
    logger.info(f"🕵️ Detecting external-dns mode from Namespace: {namespace}...")
    
    try:
        pods = core_api.list_namespaced_pod(namespace, label_selector=label_selector)
        if not pods.items:
            # Fallback: Try a looser search if strict label fails
            logger.warning(f"   - No pods found with selector '{label_selector}'. Assuming SYNC mode default.")
            return "sync"
        
        # Look at the first running pod
        pod = pods.items[0]
        logger.info(f"   - Inspecting Pod: {pod.metadata.name}")
        
        args = []
        # Find the container named 'external-dns' or take the first one
        container = next((c for c in pod.spec.containers if c.name == "external-dns"), pod.spec.containers[0])
        
        if container.args:
            args = container.args
        
        # Check arguments for the policy flag
        for arg in args:
            if "--policy=upsert-only" in arg:
                logger.info("   - Found flag '--policy=upsert-only'. Detected Mode: UPSERT-ONLY")
                return "upsert-only"
        
        logger.info("   - No upsert restriction found. Detected Mode: SYNC")
        return "sync"

    except Exception as e:
        logger.warning(f"   - Failed to detect mode (Error: {e}). Defaulting to SYNC.")
        return "sync"

def apply_resource(core_api, apps_api, resource, namespace):
    kind = resource.get("kind")
    metadata = resource.get("metadata", {})
    metadata["namespace"] = namespace
    name = metadata.get("name")

    logger.info(f"Applying {kind}: {name}...")
    try:
        if kind == "Service":
            core_api.create_namespaced_service(namespace=namespace, body=resource)
        elif kind == "Deployment":
            apps_api.create_namespaced_deployment(namespace=namespace, body=resource)
        logger.info(f"✅ Created {kind}/{name}")
    except client.exceptions.ApiException as e:
        if e.status == 409:
            logger.warning(f"⚠️  {kind}/{name} already exists. Proceeding.")
        else:
            raise

def check_dns_record(route53_client, zone_id, record_name) -> bool:
    target_dns = record_name if record_name.endswith(".") else f"{record_name}."
    try:
        response = route53_client.list_resource_record_sets(
            HostedZoneId=zone_id, StartRecordName=target_dns, MaxItems="1"
        )
        records = response.get("ResourceRecordSets", [])
        if records and records[0]["Name"] == target_dns:
            return True
    except (ClientError, BotoCoreError):
        pass
    return False

def wait_for_dns_propagation(route53_client, zone_id, record_name):
    target_dns = record_name if record_name.endswith(".") else f"{record_name}."
    logger.info(f"⏳ CREATION CHECK: Polling Route53 for: {target_dns}...")
    
    start_time = time.time()
    while time.time() - start_time < POLL_TIMEOUT_SECONDS:
        if check_dns_record(route53_client, zone_id, record_name):
            logger.info(f"✅ Found DNS Record: {target_dns}")
            return True
        time.sleep(POLL_INTERVAL_SECONDS)

    logger.error("❌ Timeout waiting for DNS creation.")
    return False

def wait_for_dns_deletion(route53_client, zone_id, record_name):
    target_dns = record_name if record_name.endswith(".") else f"{record_name}."
    logger.info(f"⏳ DELETION CHECK: Polling Route53 until {target_dns} is GONE...")
    
    start_time = time.time()
    while time.time() - start_time < POLL_TIMEOUT_SECONDS:
        if not check_dns_record(route53_client, zone_id, record_name):
            logger.info(f"✅ Record Disappeared: {target_dns}")
            return True
        logger.info("   - Record still exists...")
        time.sleep(POLL_INTERVAL_SECONDS)

    logger.error("❌ Timeout: Record persists (External-DNS failed to delete it).")
    return False

def cleanup_k8s_resources(core_api, apps_api, resources, namespace):
    logger.info("🧹 Cleaning up Kubernetes resources...")
    for res in resources:
        kind = res.get("kind")
        name = res.get("metadata", {}).get("name")
        try:
            if kind == "Service":
                core_api.delete_namespaced_service(name=name, namespace=namespace)
            elif kind == "Deployment":
                apps_api.delete_namespaced_deployment(name=name, namespace=namespace)
            logger.info(f"   - Triggered deletion for {kind}/{name}")
        except client.exceptions.ApiException as e:
            if e.status != 404:
                logger.error(f"   - Failed to delete {kind}/{name}: {e}")

def cleanup_route53_force(route53_client, zone_id, dns_name):
    target_dns = dns_name if dns_name.endswith(".") else f"{dns_name}."
    logger.info(f"🧹 FORCE CLEANUP: Checking for stale Route53 records: {target_dns}...")
    try:
        response = route53_client.list_resource_record_sets(
            HostedZoneId=zone_id, StartRecordName=target_dns, MaxItems="1"
        )
        changes = []
        for r in response.get("ResourceRecordSets", []):
            if r["Name"] == target_dns and r["Type"] in ["A", "TXT", "CNAME"]:
                changes.append({"Action": "DELETE", "ResourceRecordSet": r})
        
        if changes:
            logger.info(f"   - Found {len(changes)} records. Deleting now...")
            route53_client.change_resource_record_sets(
                HostedZoneId=zone_id, ChangeBatch={"Changes": changes}
            )
            logger.info("   - Route53 Cleaned.")
        else:
            logger.info("   - No records found. Environment is clean.")
    except Exception as e:
        logger.error(f"   - Route53 Cleanup failed: {e}")

def main():
    exit_code = 0
    
    try:
        # 1. Setup
        resources, namespace, dns_name = load_and_render_manifests(MANIFEST_PATH)
        core_api, apps_api = initialize_k8s_clients()
        r53 = boto3.client("route53", region_name=AWS_REGION)

        # 2. DETECT MODE
        mode = detect_verification_mode(core_api, EXTERNAL_DNS_NAMESPACE, EXTERNAL_DNS_SELECTOR)
        logger.info(f"🚀 STARTING VERIFICATION IN MODE: [{mode.upper()}]")

        # 3. Find Zone
        zones = r53.list_hosted_zones_by_name(DNSName=HOSTED_ZONE_NAME)
        zone_id = next((z["Id"].split("/")[-1] for z in zones.get("HostedZones", [])
                        if z["Name"] in [HOSTED_ZONE_NAME, HOSTED_ZONE_NAME + "."]), None)
        
        if not zone_id:
            raise ValueError(f"Hosted Zone {HOSTED_ZONE_NAME} not found.")

        # 4. Execution Phase
        try:
            # A. Deploy
            for res in resources:
                apply_resource(core_api, apps_api, res, namespace)

            # B. Verify Creation
            if not wait_for_dns_propagation(r53, zone_id, dns_name):
                raise RuntimeError("Creation Verification Failed")

            logger.info("✅ CREATION VERIFIED. Proceeding to Cleanup/Deletion check...")

            # C. Deletion Verification Logic
            cleanup_k8s_resources(core_api, apps_api, resources, namespace)
            
            if mode == "sync":
                logger.info("🔍 Mode is SYNC: Waiting for external-dns to auto-delete the record...")
                if wait_for_dns_deletion(r53, zone_id, dns_name):
                    logger.info("🎉 SYNC MODE VERIFIED: Record was deleted automatically.")
                else:
                    logger.error("❌ SYNC MODE FAILED: Record persisted.")
                    exit_code = 1
            
            elif mode == "upsert-only":
                logger.info("🔍 Mode is UPSERT-ONLY: Skipping auto-deletion check.")
                logger.info("🎉 UPSERT MODE VERIFIED (Creation passed).")

        except Exception as e:
            logger.error(f"Runtime Error: {e}")
            exit_code = 1

        finally:
            # 5. SAFETY NET CLEANUP
            logger.info("--- Final Safety Net Cleanup ---")
            time.sleep(5) 
            cleanup_route53_force(r53, zone_id, dns_name)

    except Exception as e:
        logger.critical(f"Fatal Setup Error: {e}")
        exit_code = 1
    
    exit(exit_code)

if __name__ == "__main__":
    main()