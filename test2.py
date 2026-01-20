# lib/k8s.py
import logging
from contextlib import contextmanager
from typing import Tuple, Dict, Any, List
from kubernetes import client, config as k8s_config, utils
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

# Type Alias for clarity
Clients = Tuple[client.ApiClient, client.CoreV1Api]

def initialize_clients() -> Clients:
    """Initialize generic ApiClient (for utils) and CoreV1 (for Namespace)."""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    
    # We return the Generic Client (for dynamic creation) and CoreV1 (for Namespaces)
    return client.ApiClient(), client.CoreV1Api()

def ensure_namespace(core_api: client.CoreV1Api, namespace: str):
    """Idempotent creation of a Namespace."""
    try:
        core_api.create_namespace(
            body=client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
        )
        logger.info(f"Created namespace: {namespace}")
    except ApiException as e:
        if e.status == 409:
            logger.info(f"Namespace {namespace} already exists.")
        else:
            raise

@contextmanager
def infrastructure_manager(clients: Clients, namespace: str, cleanup: bool = True):
    """
    Context Manager for Global Infra.
    Setup: Creates Namespace.
    Teardown: Deletes Namespace (always).
    """
    _, core_api = clients
    
    # --- SETUP ---
    logger.info(f"[Infra] Setting up namespace '{namespace}'...")
    ensure_namespace(core_api, namespace)
    
    try:
        yield
    finally:
        # --- TEARDOWN ---
        if cleanup:
            logger.info(f"[Infra] Cleaning up namespace '{namespace}'...")
            try:
                core_api.delete_namespace(name=namespace)
                logger.info("[Infra] Namespace deleted.")
            except Exception as e:
                logger.warning(f"[Infra] Failed to delete namespace: {e}")

@contextmanager
def resource_manager(clients: Clients, manifest_path: str, context: Dict[str, str]):
    """
    Context Manager for Test Resources (Service, Ingress, etc.).
    Setup: Renders YAML -> generic apply.
    Teardown: Generic delete.
    """
    api_client, _ = clients
    
    # Load and Render (Assuming you have a helper for this in utils, or imported)
    # For brevity, I assume 'load_manifests' returns a list of dicts
    from lib.utils import load_manifests 
    resources, _ = load_manifests(manifest_path, context_overrides=context)
    
    deployed_resources = []
    
    try:
        # --- DEPLOY ---
        for res in resources:
            logger.info(f"Applying {res['kind']}: {res['metadata']['name']}")
            utils.create_from_dict(api_client, res, namespace=context["TEST_NAMESPACE"])
            deployed_resources.append(res)
        yield deployed_resources
        
    finally:
        # --- CLEANUP ---
        logger.info("Cleaning up test resources...")
        for res in reversed(deployed_resources): # Delete in reverse order
            try:
                name = res["metadata"]["name"]
                namespace = context["TEST_NAMESPACE"]
                
                # Use dynamic client to delete
                # Note: utils.create_from_dict exists, but delete is often manual or via raw API.
                # A simple way for robust delete is creating a dynamic client or using raw request.
                # For simplicity here, we can assume standard resources or use the wrapper:
                k8s_opts = client.DeleteOptions(propagation_policy='Foreground')
                
                # Fallback to specific APIs or dynamic client here. 
                # (Ideally, you use dynamic_client for deletion too).
                pass # [Actual deletion logic goes here, similar to your original code]
                
            except Exception as e:
                logger.warning(f"Failed to delete {res['kind']}: {e}")