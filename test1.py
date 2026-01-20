import logging
from contextlib import contextmanager
from typing import Tuple, Dict
from kubernetes import client, config as k8s_config, utils
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

# Type Alias
Clients = Tuple[client.ApiClient, client.CoreV1Api]

def initialize_clients() -> Clients:
    """Initialize generic ApiClient (for utils) and CoreV1 (for Namespace)."""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    return client.ApiClient(), client.CoreV1Api()

def deploy_resources(clients: Clients, manifest_path: str, context: Dict[str, str]):
    """
    Simpler Deployment: Just create the resources. 
    We DO NOT track or return them for cleanup, because the Namespace deletion will handle it.
    """
    api_client, _ = clients
    
    # Import locally to avoid circular imports if utils imports k8s
    from lib.utils import load_manifests 
    
    resources, _ = load_manifests(manifest_path, context_overrides=context)
    
    for res in resources:
        kind = res.get('kind')
        name = res.get('metadata', {}).get('name')
        logger.info(f"Applying {kind}: {name}")
        
        try:
            utils.create_from_dict(api_client, res, namespace=context["TEST_NAMESPACE"])
        except utils.FailToCreateError as e:
            # Handle "Already Exists" gracefully
            if any(exc.status == 409 for exc in e.api_exceptions):
                logger.warning(f"{kind} {name} already exists. Updating/Proceeding.")
                # Optional: Add replace_namespaced_x logic here if needed
            else:
                raise

@contextmanager
def infrastructure_manager(clients: Clients, namespace: str, cleanup: bool = True):
    """
    THE MASTER CONTEXT MANAGER
    1. Setup: Creates the Namespace.
    2. Yield: Allows all tests to run inside this namespace.
    3. Teardown: Deletes the Namespace (wiping all test resources instantly).
    """
    _, core_api = clients
    
    # --- SETUP ---
    logger.info(f"[Setup] Ensuring namespace '{namespace}' exists...")
    try:
        core_api.create_namespace(
            body=client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
        )
        logger.info(f"Created namespace: {namespace}")
    except ApiException as e:
        if e.status == 409:
            logger.info(f"Namespace {namespace} already exists. Using existing.")
        else:
            raise

    try:
        yield # <-- All your tests run here
    finally:
        # --- TEARDOWN ---
        if cleanup:
            logger.info(f"[Cleanup] Deleting namespace '{namespace}'...")
            try:
                # Deleting the NS automatically deletes all Services/Ingresses inside it
                core_api.delete_namespace(name=namespace)
                logger.info("[Cleanup] Namespace deletion triggered. Resources will be garbage collected.")
            except Exception as e:
                logger.warning(f"[Cleanup] Failed to delete namespace: {e}")
        else:
            logger.info(f"[Cleanup] Skipping namespace deletion (cleanup={cleanup})")