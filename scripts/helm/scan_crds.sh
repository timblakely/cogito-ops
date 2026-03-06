TARGET_CRD="$1" # e.g., certificates.cert-manager.io

for release in $(helm list -A -q); do
  # Get namespace for the release
  ns=$(helm list -A | grep "^$release " | awk '{print $2}')
  echo "Checking Release: $release (Namespace: $ns)"
  
  # Check if this chart version contains the CRD
  if helm show crds $release -n $ns 2>/dev/null | grep -q "$TARGET_CRD"; then
    echo "Found in Release: $release (Namespace: $ns)"
    helm list -A --filter "^$release$"
  fi
done
