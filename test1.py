def get_pod_name(namespace, app_label, max_retries=5, delay_seconds=2):
    """
    Dynamically fetches the name of a running pod that matches the given app label.
    Retries a few times in case the Deployment is still spinning up the pod.
    """
    cmd = (
        "kubectl get pods -n %s -l app=%s "
        "-o jsonpath='{.items[0].metadata.name}'"
    ) % (namespace, app_label)

    for attempt in range(1, max_retries + 1):
        stdout, stderr = run_command(cmd, check=False)
        pod_name = stdout.strip()
        
        if pod_name:
            return pod_name
            
        logging.info(
            "Waiting for pod with label 'app=%s' to appear... (Attempt %d/%d)" % 
            (app_label, attempt, max_retries)
        )
        time.sleep(delay_seconds)
        
    raise RuntimeError(
        "Timeout: Could not find any pod for app '%s' in namespace '%s' after %d attempts" % 
        (app_label, namespace, max_retries)
    )

def wait_for_config_propagation(namespace, app_label, grep_cmd_arg, max_retries=30, delay_seconds=2):
    """
    1. Resolves the app label to a real Pod Name.
    2. Polls that specific Pod's Envoy Admin API for the config.
    
    Args:
        max_retries: How many times to poll the Envoy config.
        delay_seconds: How long to sleep between polls.
    """
    # Step 1: Resolve Label -> Pod Name
    # We use a small internal retry here just for the pod name resolution
    pod_name = get_pod_name(namespace, app_label)

    logging.info(
        "Checking config on Pod '%s' (Label: %s) for keyword '%s'..." % 
        (pod_name, app_label, grep_cmd_arg)
    )
    
    # Step 2: Poll Envoy Config
    cmd = (
        "kubectl exec -n %s %s -c istio-proxy -- "
        "/bin/sh -c \"curl -s http://localhost:15000/config_dump | "
        "grep '%s'\""
    ) % (namespace, pod_name, grep_cmd_arg)
    
    for attempt in range(1, max_retries + 1):
        try:
            # check=True will raise CalledProcessError if grep returns 1 (not found)
            run_command(cmd, check=True)
            logging.info("Confirmed: Config found on '%s'!" % pod_name)
            return True
        except Exception:
            # Config not found yet
            if attempt < max_retries:
                # Only sleep if we have more retries left
                time.sleep(delay_seconds)
            
    raise RuntimeError(
        "Timeout: Config '%s' never appeared on '%s' after %d attempts (%ds total)" % 
        (grep_cmd_arg, pod_name, max_retries, max_retries * delay_seconds)
    )