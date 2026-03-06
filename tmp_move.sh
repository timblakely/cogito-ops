#!/bin/bash
set -e

mv kubernetes/flux/meta/repositories/app-template.yaml kubernetes/flux/meta/app-template.yaml
mv kubernetes/flux/meta/repositories/cert-manager.yaml kubernetes/apps/cluster-infra/cert-manager/repo.yaml
mv kubernetes/flux/meta/repositories/cilium.yaml kubernetes/apps/cilium/cilium/repo.yaml
mv kubernetes/flux/meta/repositories/cloudflare-dns.yaml kubernetes/apps/network/cloudflare-dns/repo.yaml
mv kubernetes/flux/meta/repositories/cloudnative-pg.yaml kubernetes/apps/database/cloudnative-pg/repo.yaml
mv kubernetes/flux/meta/repositories/coredns.yaml kubernetes/apps/kube-system/coredns/repo.yaml
mv kubernetes/flux/meta/repositories/csi-driver-nfs.yaml kubernetes/apps/storage/csi-driver-nfs/repo.yaml
mv kubernetes/flux/meta/repositories/dragonfly-operator.yaml kubernetes/apps/database/dragonfly/repo.yaml
mv kubernetes/flux/meta/repositories/envoy-gateway.yaml kubernetes/apps/envoy-system/envoy/repo.yaml
mv kubernetes/flux/meta/repositories/external-dns.yaml kubernetes/apps/network/unifi-dns/repo.yaml
mv kubernetes/flux/meta/repositories/external-secrets.yaml kubernetes/apps/cluster-infra/external-secrets/repo.yaml
mv kubernetes/flux/meta/repositories/fluent-bit.yaml kubernetes/apps/observability/fluent-bit/repo.yaml
mv kubernetes/flux/meta/repositories/flux-instance.yaml kubernetes/apps/flux-system/flux-instance/repo.yaml
mv kubernetes/flux/meta/repositories/flux-operator.yaml kubernetes/apps/flux-system/flux-operator/repo.yaml
mv kubernetes/flux/meta/repositories/grafana-operator.yaml kubernetes/apps/observability/grafana-operator/repo.yaml
mv kubernetes/flux/meta/repositories/kube-prometheus-stack.yaml kubernetes/apps/observability/kube-prometheus-stack/repo.yaml
mv kubernetes/flux/meta/repositories/metrics-server.yaml kubernetes/apps/kube-system/metrics-server/repo.yaml
mv kubernetes/flux/meta/repositories/multus.yaml kubernetes/apps/network/multus/repo.yaml
mv kubernetes/flux/meta/repositories/openebs.yaml kubernetes/apps/storage/openebs/repo.yaml
mv kubernetes/flux/meta/repositories/plugin-barman-cloud.yaml kubernetes/apps/database/plugin-barman-cloud/repo.yaml
mv kubernetes/flux/meta/repositories/reloader.yaml kubernetes/apps/cluster-infra/reloader/repo.yaml
mv kubernetes/flux/meta/repositories/rook-ceph-cluster.yaml kubernetes/apps/rook-ceph/rook-ceph-cluster/repo.yaml
mv kubernetes/flux/meta/repositories/rook-ceph.yaml kubernetes/apps/rook-ceph/rook-ceph/repo.yaml
mv kubernetes/flux/meta/repositories/smartctl-exporter.yaml kubernetes/apps/observability/smartctl-exporter/repo.yaml
mv kubernetes/flux/meta/repositories/snapshot-controller.yaml kubernetes/apps/storage/snapshot-controller/repo.yaml
mv kubernetes/flux/meta/repositories/spegel.yaml kubernetes/apps/cluster-infra/spegel/repo.yaml
mv kubernetes/flux/meta/repositories/victoria-logs.yaml kubernetes/apps/observability/victoria-logs/repo.yaml
rmdir kubernetes/flux/meta/repositories
