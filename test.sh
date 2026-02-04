#!/bin/bash

echo "Starting reproduction loop..."
count=0

while true; do
  ((count++))
  echo "----------------------------------------"
  echo "Attempt #$count"
  echo "----------------------------------------"

  # Run the test and capture all output (stdout + stderr)
  # We use 'uv run' as you requested.
  output=$(uv run main.py 2>&1)
  
  # Print output to screen so you can see progress
  echo "$output"

  # Search for the specific failure string
  if echo "$output" | grep -q "Too Fast"; then
    echo ""
    echo "🔥 ISSUE REPRODUCED on Attempt #$count!"
    echo "The script has stopped so you can analyze the logs above."
    break
  fi

  # Optional: If the script fails for other reasons (Python crash), stop too.
  if [[ $? -ne 0 ]]; then
     # Use this only if you want to stop on ANY failure, not just "Too Fast"
     # echo "Script crashed!"
     # break
     :
  fi
  
  # Tiny sleep to ensure we don't accidentally throttle local OS resources
  # (though usually for race conditions, faster is better)
  sleep 1
done