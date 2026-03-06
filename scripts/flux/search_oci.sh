#!/bin/bash

# Define the CRD you are hunting for
TARGET_CRD="$1" # Change this to your conflicting CRD

BASE_DIR="/tmp/flux-oci-audit"

echo "🔍 Fetching OCI Repositories via kubectl..."

# Use kubectl to get the actual OCI sources Flux is using
kubectl get ocirepositories.source.toolkit.fluxcd.io -A -o json | jq -c '.items[]' | while read -r repo; do
    NAME=$(echo "$repo" | jq -r '.metadata.name')
    NS=$(echo "$repo" | jq -r '.metadata.namespace')
    URL=$(echo "$repo" | jq -r '.spec.url')
    
    # Get the specific revision (tag or sha256)
    REV=$(echo "$repo" | jq -r '.status.artifact.revision // "empty"')
    DIR_REV=$(echo "$REV" | sed 's/:/-/g') 
    
    if [ "$REV" == "empty" ]; then
        echo "⚠️  Skipping $NS/$NAME: No artifact revision found."
        continue
    fi

    # Build the full OCI URL
    if [[ "$REV" == sha256* ]]; then
        FULL_URL="${URL}@${REV}"
    else
        FULL_URL="${URL}:${REV}"
    fi

    EXPORT_PATH="$BASE_DIR/$NS/$NAME/$DIR_REV"
    
    echo "----------------------------------------------------------"
    echo "📦 Source: $NS/$NAME"
    echo "📌 Target: $FULL_URL"

    # --- CACHING & EXTRACTION LOGIC ---
    if [ -d "$EXPORT_PATH" ] && [ "$(ls -A "$EXPORT_PATH" 2>/dev/null)" ]; then
        echo "♻️  Found cached version. Skipping download."
    else
        echo "📥 Extracting..."
        mkdir -p "$EXPORT_PATH"
        TEMP_TGZ="/tmp/flux_audit_${NAME}_${DIR_REV}.tgz"
        
        # Strategy 1: Default (Local Creds)
        if ! flux pull artifact "$FULL_URL" --output "$TEMP_TGZ" > /dev/null 2>&1; then
             echo "🔄 Default pull failed. Strategy 2: Anonymous..."
             
             # Strategy 2: Forced Anonymous (Bypasses ~/.docker/config.json)
             if ! flux pull artifact "$FULL_URL" --creds "anonymous:anonymous" --output "$TEMP_TGZ" > /dev/null 2>&1; then
                 echo "❌ Failed to pull artifact via Flux CLI."
                 rm -rf "$EXPORT_PATH"
                 continue
             fi
        fi
        
        if [ -f "$TEMP_TGZ" ]; then
            tar -xzf "$TEMP_TGZ" -C "$EXPORT_PATH"
            rm "$TEMP_TGZ"
            echo "✅ Successfully unpacked to $EXPORT_PATH"
        fi
    fi

    # --- SEARCH LOGIC ---
    # We search the extracted directory for the CRD name
    MATCH=$(grep -rl "kind: CustomResourceDefinition" "$EXPORT_PATH" 2>/dev/null | xargs grep -l "name: $TARGET_CRD" 2>/dev/null)
    
    if [ ! -z "$MATCH" ]; then
        echo "🎯 MATCH FOUND!"
        echo "   File: $MATCH"
        # Print the API version and group for conflict comparison
        grep -E "version:|group:" "$MATCH" | head -n 5
    else
        echo "⚪ No matching CRD."
    fi

done

echo "----------------------------------------------------------"
echo "Done. Audit files located in $BASE_DIR"
