from kubernetes import client, config
from kubernetes.client.rest import ApiException

# 1. Load Config (In-Cluster)
try:
    config.load_incluster_config()
except config.ConfigException:
    config.load_kube_config() # For local testing

# 2. Clients
v1 = client.CoreV1Api()
rbac_v1 = client.RbacAuthorizationV1Api()
networking_v1 = client.NetworkingV1Api()
custom_objs = client.CustomObjectsApi() # For Istio

# 3. Constants
VERIFICATION_NS = "verification-external-dns"
SA_NAME = "external-dns"
SA_NAMESPACE = "external-dns"
STRICT_ROLE_NAME = "verification-job-rules"

def run_verification_flow():
    print(f"--- Starting Verification in {VERIFICATION_NS} ---")

    # A. Create Namespace
    print(f"1. Creating Namespace: {VERIFICATION_NS}...")
    ns_body = client.V1Namespace(metadata=client.V1ObjectMeta(name=VERIFICATION_NS))
    try:
        v1.create_namespace(body=ns_body)
    except ApiException as e:
        if e.status == 409:
            print(" -> Namespace already exists.")
        else:
            raise

    # B. Bootstrap Permissions (Self-Binding)
    print("2. Bootstrapping Strict Permissions...")
    # We use a Dict here to avoid import issues with V1Subject
    subject_dict = {
        "kind": "ServiceAccount",
        "name": SA_NAME,
        "namespace": SA_NAMESPACE
    }

    binding = client.V1RoleBinding(
        metadata=client.V1ObjectMeta(name="verification-runner", namespace=VERIFICATION_NS),
        subjects=[subject_dict],
        role_ref=client.V1RoleRef(
            kind="ClusterRole",
            name=STRICT_ROLE_NAME, # <--- Binding the Strict Rules
            api_group="rbac.authorization.k8s.io"
        )
    )
    
    try:
        rbac_v1.create_namespaced_role_binding(namespace=VERIFICATION_NS, body=binding)
        print(" -> Permissions bound successfully.")
    except ApiException as e:
        if e.status == 409:
            print(" -> Binding already exists.")
        else:
            print(f"!!! Error binding permissions: {e}")
            raise

    # C. Create Ingress (Strict Mode: Blind Create)
    print("3. Creating Ingress (Blind)...")
    ingress_manifest = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": "test-ingress", 
            "namespace": VERIFICATION_NS,
            "annotations": {"external-dns.alpha.kubernetes.io/hostname": "test.example.com"}
        },
        "spec": {
            "rules": [{
                "host": "test.example.com",
                "http": {"paths": [{"path": "/", "pathType": "Prefix", "backend": {"service": {"name": "test-svc", "port": {"number": 80}} }}]}
            }]
        }
    }

    try:
        networking_v1.create_namespaced_ingress(namespace=VERIFICATION_NS, body=ingress_manifest)
        print(" -> Ingress created.")
    except ApiException as e:
        if e.status == 409:
            print(" -> Ingress already exists (Cannot update due to strict permissions).")
        else:
            raise

    # D. Create Istio Gateway (Custom Resource)
    print("4. Creating Istio Gateway (Blind)...")
    gateway_manifest = {
        "apiVersion": "networking.istio.io/v1alpha3",
        "kind": "Gateway",
        "metadata": {"name": "test-gateway", "namespace": VERIFICATION_NS},
        "spec": {
            "selector": {"istio": "ingressgateway"},
            "servers": [{"port": {"number": 80, "name": "http", "protocol": "HTTP"}, "hosts": ["*"]}]
        }
    }

    try:
        custom_objs.create_namespaced_custom_object(
            group="networking.istio.io",
            version="v1alpha3",
            namespace=VERIFICATION_NS,
            plural="gateways",
            body=gateway_manifest
        )
        print(" -> Gateway created.")
    except ApiException as e:
        if e.status == 409:
            print(" -> Gateway already exists.")
        else:
            raise

def cleanup():
    print(f"\n--- Cleaning Up {VERIFICATION_NS} ---")
    try:
        v1.delete_namespace(name=VERIFICATION_NS)
        print(" -> Namespace deleted.")
    except ApiException as e:
        if e.status == 404:
            print(" -> Namespace already gone.")
        else:
            print(f"!!! Error deleting namespace: {e}")

if __name__ == "__main__":
    try:
        run_verification_flow()
        # verify_dns_propagation() # <--- Your logic here
    finally:
        cleanup()