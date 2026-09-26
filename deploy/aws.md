"""Hub1z AWS hosting notes.

## Starting architecture (dev + prod EC2)

1. **EC2** — one dev and one prod instance, each running the web and
   PostgreSQL containers with Docker Compose.
   The current deployment builds the image directly on EC2; no ECR repository
   or image registry is required yet.
2. **EBS** — persistent per-instance storage for the PostgreSQL Docker volume.
3. **S3** — two private document buckets:
   - `AWS_S3_PLATFORM_BUCKET` for platform-owned files
   - `AWS_S3_OPERATOR_BUCKET` for operator-owned files
4. **Nginx + Let's Encrypt (Certbot, Route 53 DNS plugin)** — reverse proxy
   and wildcard TLS for `hub1z.com` and `*.hub1z.com`, since Hub1z resolves
   each operator by the request `Host` header.
5. **Route 53** — hosted zone for `hub1z.com`, including SES DKIM records and
   a wildcard `A` record for operator subdomains.
6. **SES** — transactional email; starts in sandbox mode until production
   access is approved.
7. **SSM** — manage EC2 instances without opening SSH where possible.
8. **CloudWatch** — logs, disk alarms, and container health monitoring.

The detailed procedure, including the dev/prod split, is in
`deploy/aws-setup.md`.

## Database trade-off

PostgreSQL runs inside Docker on each EC2 host rather than RDS. This avoids
the RDS monthly cost but makes that EC2 instance a single point of failure
for its own data. The operator must manage:

- EBS disk capacity
- PostgreSQL upgrades
- Daily `pg_dump` backups to S3
- Restore testing
- Recovery after EC2 failure

RDS remains a future upgrade path, not a prerequisite for the current setup.

## Future production path

When Hub1z needs high availability or reduced database operations, move the
PostgreSQL database to RDS, add an ALB in front of multiple EC2 instances,
move images to ECR, and add CloudWatch alarms. The application continues to
use `DATABASE_URL`, so the migration is a configuration/deployment change
rather than a product-model change.
"""
