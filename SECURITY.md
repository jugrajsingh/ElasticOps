# Security Policy

## Supported versions
ElasticOps is pre-1.0; security fixes are applied to the latest `main` and the most recent release.

## Reporting a vulnerability
Please report security issues **privately** — do not open a public issue.
Email **jugrajskhalsa@gmail.com** with details and reproduction steps. You can expect an
acknowledgement within a few days and a coordinated disclosure once a fix is available.

## Scope notes
- ElasticOps stores Elasticsearch cluster credentials **encrypted at rest** (Fernet).
- The JWT signing secret and the Fernet key auto-generate into a gitignored
  `.elasticops-secrets.json`; set `AUTH__JWT_SECRET` / `SECURITY__ENCRYPTION_KEY` in production.
- Run ElasticOps behind your own authentication/reverse-proxy when exposed beyond localhost.
