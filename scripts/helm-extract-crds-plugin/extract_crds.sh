#!/usr/bin/env sh
set -e
cat <&0 > /tmp/crds.yaml
echo "ASDJFIOJASDI: [$(which yq)]" >> /tmp/debug.txt
cat /tmp/crds.yaml | yq ea -e 'select(.kind == "CustomResourceDefinition")' || echo '---'
