# NuQ schema provenance

`nuq.cnpg.sql` is derived from Firecrawl's `apps/nuq-postgres/nuq.sql`.

- Firecrawl API image: `2.10.1@sha256:651e0c8f73006ad13b0e926ba4eeb3358a953ceffca43b32bd149ee95c3574fe`
- Source commit: `3d6342b84d014be47819f0cf06a293fcd377aa79`
- Upstream SHA-256: `44edb370cfc2601076e174c5461ffdfda8a1051b3c2a87c1b5231d002a66ee77`
- Derived SHA-256: `08cd0a2f90a42246c2b44afe97de8b836548bb3f815c2869dbc3e6984b81d9d6`

The derived file is upstream SQL with only lines beginning `ALTER SYSTEM ` and
the `SELECT pg_reload_conf();` line removed. CNPG owns equivalent PostgreSQL
configuration declaratively.
