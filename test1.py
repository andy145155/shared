def wait_for_header_response(namespace, client_pod_name, target_url, max_retries=30):
    """
    Polls the endpoint until the 'retry-after' header appears in the response.
    Fixed to avoid pipe (|) syntax errors in kubectl exec.
    """
    logging.info("Warming up Header Logic: Polling %s for 'retry-after'...", target_url)
    
    # 1. REMOVED "| grep". Just run curl and capture everything (stderr included via 2>&1 if needed, 
    # but run_command usually separates them. Let's just capture stdout/stderr).
    # We use -I (Head) or -v (Verbose) to see headers. -I is cleaner if endpoint supports it, 
    # but -v is safer for debugging.
    cmd = (
        f"kubectl exec -n {namespace} {client_pod_name} -- "
        f"curl -s -v -H 'Connection: close' '{target_url}'"
    )

    for attempt in range(1, max_retries + 1):
        # We allow check=False because curl might return non-zero if the 503 is treated as fail 
        # (though -s usually suppresses that).
        stdout, stderr = run_command(cmd, check=False)
        
        # Combine output to search for headers (curl -v prints headers to stderr often)
        full_output = stdout + stderr
        
        # 2. Python-side Check (Case Insensitive)
        if "retry-after" in full_output.lower():
            logging.info("Success! 'retry-after' header detected in response.")
            return True
            
        logging.info("Header not yet present... (Attempt %d/%d)", attempt, max_retries)
        time.sleep(1)
            
    raise RuntimeError("Timeout: Target is returning 503, but MISSING the 'retry-after' header.")