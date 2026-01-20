from kubernetes import client, config, utils
from kubernetes.client.rest import ApiException

# Load in-cluster config (uses the ServiceAccount token automatically)
config.load_incluster_config()

v1 = client.CoreV1Api()
rbac_v1 = client.RbacAuthorizationV1Api()

VERIFICATION_NS = "verification-external-dns"
SA_NAME = "external-dns"
SA_NAMESPACE = "external-dns"

def create_ephemeral_env():
    # 1. Create the Namespace
    print(f"Creating namespace: {VERIFICATION_NS}...")
    ns_body = client.V1Namespace(metadata=client.V1ObjectMeta(name=VERIFICATION_NS))
    try:
        v1.create_namespace(body=ns_body)
    except ApiException as e:
        if e.status == 409:
            print("Namespace already exists, proceeding...")
        else:
            raise

    # 2. BOOTSTRAP: Self-Bind Admin rights inside the new namespace
    # This uses the 'create rolebindings' permission we gave in the ClusterRole
    print("Bootstrapping Admin permissions...")
    binding = client.V1RoleBinding(
        metadata=client.V1ObjectMeta(name="verification-admin", namespace=VERIFICATION_NS),
        subjects=[client.V1Subject(
            kind="ServiceAccount",
            name=SA_NAME,
            namespace=SA_NAMESPACE
        )],
        role_ref=client.V1RoleRef(
            kind="ClusterRole",
            name="admin", # We use the built-in K8s admin role
            api_group="rbac.authorization.k8s.io"
        )
    )
    try:
        rbac_v1.create_namespaced_role_binding(namespace=VERIFICATION_NS, body=binding)
        print("Admin access granted successfully.")
    except ApiException as e:
        if e.status == 409:
            print("Binding already exists.")
        else:
            raise

def check_main_pods():
    # 3. List Pods in the Home Namespace
    # This uses the 'pod-reader' Role we created
    print(f"Checking pods in {SA_NAMESPACE}...")
    pods = v1.list_namespaced_pod(SA_NAMESPACE)
    for pod in pods.items:
        print(f"Found pod: {pod.metadata.name} ({pod.status.phase})")

def cleanup():
    # 4. Delete the Namespace
    # This uses the restricted 'delete' permission in the ClusterRole
    print(f"Deleting namespace {VERIFICATION_NS}...")
    try:
        v1.delete_namespace(name=VERIFICATION_NS)
        print("Namespace deleted.")
    except ApiException as e:
        print(f"Error deleting namespace: {e}")

# --- Execution Flow ---
try:
    create_ephemeral_env()
    check_main_pods()
    
    # ... Run your Ingress/Gateway creation logic here ...
    # utils.create_from_yaml(k8s_client, "ingress.yaml", namespace=VERIFICATION_NS)
    
finally:
    # Always clean up, even if tests fail
    cleanup()