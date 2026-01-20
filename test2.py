import logging
from contextlib import contextmanager
from typing import Tuple, Dict
from kubernetes import client, config as k8s_config, utils
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

Clients = Tuple[client.ApiClient, client.CoreV1Api]

def initialize_clients() -> Clients:
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    return client.ApiClient(), client.CoreV1Api()

def deploy_resources(clients: Clients, manifest_path: str, context: Dict[str, str]):
    """
    Simply creates resources. No cleanup logic needed here.
    """
    api_client, _ = clients
    from lib.utils import load_manifests
    resources, _ = load_manifests(manifest_path, context_overrides=context)
    
    for res in resources:
        logger.info(f"Applying {res['kind']}: {res['metadata']['name']}")
        # Automatically handles Service, Ingress, Gateway, etc.
        utils.create_from_dict(api_client, res, namespace=context["TEST_NAMESPACE"])

@contextmanager
def disposable_namespace(clients: Clients, namespace_name: str):
    """
    Context Manager:
    [Enter] -> Create Namespace
    [Yield] -> Run Test
    [Exit]  -> Delete Namespace (Everything inside dies)
    """
    _, core_api = clients
    
    # 1. Create
    logger.info(f"[Setup] Creating namespace: {namespace_name}")
    try:
        core_api.create_namespace(
            body=client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace_name))
        )
    except ApiException as e:
        if e.status != 409: # Ignore "Already Exists", raise others
            raise

    try:
        yield
    finally:
        # 2. Delete (Cleanup)
        logger.info(f"[Cleanup] Deleting namespace: {namespace_name}")
        try:
            core_api.delete_namespace(name=namespace_name)
            logger.info("[Cleanup] Namespace deletion triggered.")
        except Exception as e:
            logger.warning(f"[Cleanup] Failed to delete namespace: {e}")