# Firecrawl on CNPG

## Goal

Run Firecrawl with its complete, version-matched NuQ PostgreSQL schema while
retaining the existing CloudNativePG cluster and PgBouncer pooler. Do not
claim the backup/recovery path is preserved until WAL archiving and a fresh
base backup both succeed after the rebuild.

## Design

Use CNPG's native extension-image support rather than replacing the PostgreSQL
operand image.

1. Pin Firecrawl API and Playwright images to the same explicit upstream
   release and digest.
2. Package `pg_cron` for PostgreSQL 18 as a CNPG extension image. The image
   contains only the extension shared library, control file, and SQL files; it
   does not replace the CNPG operand image.
   - It must be ABI-compatible with PostgreSQL 18 and the Trixie-based CNPG
     operand image.
   - It must publish `amd64` and `arm64` variants and be digest-pinned.
3. Attach that image to `firecrawl-db` through
   `spec.postgresql.extensions`, and configure:

   ```yaml
   postgresql:
     shared_preload_libraries:
       - pg_cron
     parameters:
       cron.database_name: app
   ```

4. Vendor Firecrawl's complete
   `apps/nuq-postgres/nuq.sql` from the source commit that built the pinned API
   image. Do not maintain a hand-written subset or fetch the schema at runtime.
   - The file cannot be executed byte-for-byte: upstream contains `ALTER
     SYSTEM` tuning and `pg_reload_conf()`, which would create configuration
     drift against the shared CNPG component's declarative PostgreSQL settings.
   - Generate a documented, mechanically derived `nuq.cnpg.sql` that removes
     only that tuning block and reload command; preserve all upstream NuQ
     types, tables, indexes, and `pg_cron` schedules.
   - Record the upstream release, commit, upstream-file SHA-256, derived-file
     SHA-256, and transformation method in a sibling `NUQ-SOURCE.md`.
5. Expose `nuq.cnpg.sql` through a stable ConfigMap and run it with CNPG's
   `bootstrap.initdb.postInitApplicationSQLRefs`. The bootstrap executes as
   the CNPG superuser after it creates the `app` database.
6. Use a second, repository-owned `nuq-grants.sql` reference after the derived
   upstream SQL. Grant the CNPG application role (`app`) `USAGE` on schema
   `nuq`, `USAGE` on its enum types, and required table privileges. Firecrawl
   connects as `app` while bootstrap SQL runs as `postgres`.

## Implementation sequence

1. Remove the current partial `nuq-core.sql` bootstrap and any ad-hoc grants or
   migration Jobs used to recover from it.
2. Create and publish the PostgreSQL 18 `pg_cron` extension image. Pin its
   digest in the Firecrawl CNPG patch.
3. Add the extension image and preload/database settings using the existing
   CNPG extension pattern used by `knowledge` and `immich`.
4. Add the complete, release-matched upstream SQL, the documented derivation,
   and a separate grants file to this directory.
5. Generate stable ConfigMaps from both SQL files and reference them, in order,
   from the CNPG `initdb` bootstrap configuration. Validate the rendered
   ConfigMap payload checksums before deployment; this catches Kustomize or
   substitution damage to PostgreSQL dollar-quoted strings.
6. Validate the full Flux render—including extension image reference,
   ConfigMaps, Cluster patch, and grants—before deleting the current database.
7. Because initdb hooks run only for a new cluster, delete and recreate the
   Firecrawl CNPG Cluster and its data PVC only after the new GitOps revision is
   committed and Flux has rendered it successfully. Firecrawl currently has no
   data to preserve.
8. Wait for the old PVC/PV deletion to complete, then let Flux recreate the
   database. Do not use imperative schema changes except for emergency recovery.
9. Do not declare rollout complete until ContinuousArchiving is healthy and a
   new base backup completes successfully.

## Verification

1. Flux Kustomization and HelmRelease are Ready.
2. `firecrawl-db` is Ready; ContinuousArchiving is true; and a new base backup
   completes successfully.
3. `SELECT extname FROM pg_extension` shows `pgcrypto` and `pg_cron`.
4. `SHOW shared_preload_libraries` includes `pg_cron`, and
   `SHOW cron.database_name` returns `app`.
5. The NuQ tables, indexes, and cron jobs from upstream SQL exist in `app`.
6. The `app` role has schema/type/table privileges required by Firecrawl.
7. RabbitMQ, Playwright, and the Firecrawl API are Ready; inspect RabbitMQ
   logs explicitly rather than assuming its health from database readiness.
8. A `POST /v2/scrape` request succeeds, followed by an Open WebUI `fetch_url`
   check through the in-cluster Firecrawl service.

## Update policy

Treat the Firecrawl image digest and NuQ SQL as one versioned unit. Update
them together, review the upstream schema diff, and test the change against a
fresh CNPG bootstrap before promoting it.
