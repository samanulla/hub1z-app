# Hub1z Webapp Deployment Runbook

This runbook provides step-by-step instructions for setting up the Hub1z Flask
webapp on AWS EC2 instances for dev and production environments.

### Planned Environment Split
- **Production:** retain the current EC2 instance and its Elastic IP, Nginx,
  certificate and `hub1z.com` operator domains; move PostgreSQL to private RDS.
- **Development:** create a separate EC2 instance with its own local PostgreSQL,
  `dev.hub1z.com` and `<slug>.dev.hub1z.com` domains, secrets and document buckets.
- Reuse the current instance's VPC for RDS. Do not create an unrelated VPC from
  the example below unless you also plan private connectivity between VPCs.
- Keep `MARKETPLACE_ENABLED=false`. Do not copy production data or credentials
  into dev. Use `FLASK_ENV=production` on both internet-facing instances; dev
  is a deployment environment, not permission to expose Flask debug mode.
- Follow section 4.10 for RDS and cutover before treating the current VM as
  production. This guide does not provision or change any resources itself.

## Prerequisites
- AWS account with appropriate permissions
- Domain: hub1z.com (owned and configured in Route 53)
- SSH key pair for EC2 access
- GitHub repository access

## 0. Cost Considerations and Service Selection
This deployment is designed for a low-to-moderate volume multi-operator site
with affordable and secure AWS services.

- Prefer the Mumbai region (`ap-south-1`) for lower latency for India-based operators and members.
- Use `t3.micro` for dev if eligible under the free tier. For production, `t3.small` is a low-cost but reliable choice; move to `t3.medium` as operator/traffic volume grows.
- Keep PostgreSQL in Docker Compose on dev. Use RDS PostgreSQL on production
  for managed backups and point-in-time recovery. Single-AZ is cheaper but
  does not provide Multi-AZ failover; choose Multi-AZ when availability warrants it.
- Use `gp3` EBS storage for cost-efficient persistent disk, starting with 20 GB (PostgreSQL data plus document staging live here).
- Use Nginx + Let's Encrypt (via Certbot) for free wildcard SSL without ALB
  running costs. ACM with an ALB also supports wildcard certificates but adds
  load-balancer costs; it is an alternative when availability/scale warrants it.
- Use Route 53 only if the domain is already managed there; otherwise keep DNS costs minimal with an existing registrar.
- Use Security Groups and IP-restricted SSH to improve security without extra service spend.

### Estimated Chargeable Services
- EC2 t3.micro dev: check current account-specific free-tier eligibility; builds
  may need swap or a larger instance. Existing account age matters.
- EC2 t3.small prod: about $15–20/mo
- EBS gp3 20 GB (per instance): about $2–3/mo
- Route 53 hosted zone: $0.50/mo plus a few cents per million DNS queries
- Public IPv4 / Elastic IP: charged even when attached to a running instance;
  budget roughly $3.65/month per address at $0.005/hour, subject to current pricing.
- RDS PostgreSQL: separately budget instance hours, storage, backup overages and
  optional Multi-AZ. Compare Mumbai prices in AWS Pricing Calculator rather than
  assuming an EC2 free-tier allowance also covers RDS.
- Let's Encrypt via Certbot: free public TLS certificates, including wildcard
- S3 (two document buckets, low volume): under $1–2/mo
- SES: pennies per 1,000 emails at low volume
- CloudWatch basic monitoring: free for standard EC2 metrics; logs may incur small charges if used heavily
- Data transfer: minimal for low traffic; expect under $1–5/mo for low volume

> Confirm current AWS free-tier eligibility and pricing for your account/region — the above are approximate starting-point estimates, not a quote.

> Target: separate dev EC2 with local PostgreSQL, existing production EC2 with
> private RDS PostgreSQL, Nginx with environment-specific wildcard certificates,
> and separate private S3 buckets. No NAT Gateway is required just for EC2-to-RDS
> connectivity in the same VPC.

## 0.5 Infrastructure as Code
This repository does not yet include Terraform. If you want reproducible
environment creation and teardown, add Terraform under `infra/` mirroring the
network/storage/compute modules outlined in `deploy/aws.md`, with
`env = "dev"` and `env = "prod"` variants. Until then, follow the manual
console steps below.

## 1. Create VPC and Networking

### 1.1 Create VPC
1. Go to AWS Console > VPC > Create VPC
2. Name: `hub1z-vpc`
3. IPv4 CIDR: `10.20.0.0/16`
4. Enable DNS hostnames
5. Create

### 1.2 Create Subnets
1. Create Public Subnet:
   - Name: `hub1z-public-subnet`
   - VPC: `hub1z-vpc`
   - Availability Zone: `ap-south-1a` (Mumbai)
   - IPv4 CIDR: `10.20.1.0/24`
2. Create a second public subnet in another AZ (needed later if you add an ALB or a second instance):
   - Name: `hub1z-public-subnet-b`
   - Availability Zone: `ap-south-1b`
   - IPv4 CIDR: `10.20.2.0/24`
3. Create Private Subnet for RDS:
   - Name: `hub1z-private-subnet`
   - Availability Zone: `ap-south-1a`
   - IPv4 CIDR: `10.20.11.0/24`
4. Create a second private subnet in `ap-south-1b`:
  - Name: `hub1z-private-subnet-b`
  - IPv4 CIDR: `10.20.12.0/24`
5. Associate both private subnets with a private route table containing only
  the VPC local route. RDS needs a DB subnet group spanning at least two AZs,
  even for a Single-AZ DB instance. Use unused CIDRs within the existing VPC
  if its CIDR differs from this example.

### 1.3 Create Internet Gateway
1. VPC > Internet Gateways > Create
2. Name: `hub1z-igw`
3. Attach to `hub1z-vpc`

### 1.4 Create Route Table
1. VPC > Route Tables > Create
2. Name: `hub1z-public-rt`
3. VPC: `hub1z-vpc`
4. Routes > Edit routes:
   - Add route: `0.0.0.0/0` -> `igw-xxxxxxxx` (choose the attached Internet Gateway resource ID)
   - Do not remove the default `10.20.0.0/16 local` route
5. Subnet associations > Edit:
   - Associate `hub1z-public-subnet` and `hub1z-public-subnet-b`

### 1.5 Validate Public Subnet and Public IP
1. Confirm both public subnets are associated with `hub1z-public-rt`.
2. Confirm `hub1z-public-rt` has:
   - `10.20.0.0/16` ➜ `local`
   - `0.0.0.0/0` ➜ your Internet Gateway (`igw-...`)
3. Confirm the IGW is attached to `hub1z-vpc`.
4. When launching an instance in `hub1z-public-subnet`, set Auto-assign public IP to `Enable` for direct SSH/browser access by public IP.
5. If Auto-assign public IP is disabled, you can only access the instance through a VPN/bastion host or Systems Manager Session Manager.

## 2. Security Groups

### 2.1 Dev Security Group
1. EC2 > Security Groups > Create
2. Name: `hub1z-dev-sg`
3. VPC: `hub1z-vpc`
4. Inbound rules:
   - SSH: 22, Source: Your IP (restrict to your IP for security)
   - HTTP: 80, Source: `0.0.0.0/0`
   - HTTPS: 443, Source: `0.0.0.0/0`
  - Do not open port 8000 publicly. Use Nginx or an SSH tunnel for initial testing.

### 2.2 Prod Security Group
1. Similar to dev, but name: `hub1z-prod-sg`
2. Restrict SSH to specific IPs, or omit it and use SSM
3. No port 8000 open publicly — the app is reached only through Nginx on 80/443

In both security groups, do not open PostgreSQL ports (5432/5433) to
`0.0.0.0/0`. The web container reaches PostgreSQL over the private Docker
Compose network; no host firewall rule should expose it externally.

### 2.3 RDS Security Group
Create `hub1z-prod-rds-sg` in the production EC2 VPC. Allow inbound PostgreSQL
TCP **5432** from **`hub1z-prod-sg` (security group ID)** only, not an IP range
and not `hub1z-dev-sg`. Allow outbound 5432 from the production EC2 security
group to the RDS security group if EC2 outbound rules are restricted. Keep
RDS public accessibility **No**. Confirm the current EC2 actually has the
production security group attached before connecting.

## 3. Launch EC2 Instances

### 3.1 Dev Instance
1. EC2 > Instances > Launch instances
2. Name: `hub1z-dev`
3. AMI: Amazon Linux 2023
4. Instance type: `t3.micro` if sufficient; verify free-tier eligibility
5. Key pair: Select your SSH key
6. VPC: `hub1z-vpc`
7. Subnet: `hub1z-public-subnet`
8. Auto-assign public IP: Enable
9. Security group: `hub1z-dev-sg`
10. Storage: 20 GB gp3
11. Launch

### 3.2 Prod Instance
Reuse the current VM rather than launching another production instance.
Rename its Name tag to `hub1z-prod`, attach `hub1z-prod-sg`, and retain its
Elastic IP and existing DNS. Consider resizing to `t3.small`; resizing requires
a stop/start and an outage. Keep an EBS snapshot before significant changes.

## 4. Initial Server Setup

### 4.1 Connect to Instance
```bash
ssh -i your-key.pem ec2-user@<public-ip>
```

### 4.2 Update System
```bash
sudo dnf update -y
```

### 4.3 Install Docker and Docker Compose
Install Docker first. Amazon Linux 2023 may not include the Docker Compose
plugin in the `docker` package, so install the official plugin separately.
AL2023 also preinstalls `curl-minimal`, which
conflicts with the full `curl` package and aborts the whole `dnf install`
transaction (including `docker`) if you request `curl` explicitly — omit it,
since `curl-minimal` already provides the `curl` command used later in this
runbook:
```bash
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user
```

Install the Compose v2 plugin for the current user:
```bash
mkdir -p "$HOME/.docker/cli-plugins"
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o "$HOME/.docker/cli-plugins/docker-compose"
chmod +x "$HOME/.docker/cli-plugins/docker-compose"
```

Install Buildx as well. Compose uses Buildx for `docker compose build`, even
when the image is built locally on EC2:
```bash
BUILDX_VERSION=$(curl -fsSL https://api.github.com/repos/docker/buildx/releases/latest \
  | sed -n 's/.*"tag_name": "\(v[^"]*\)".*/\1/p' | head -1)
curl -fL "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-amd64" \
  -o "$HOME/.docker/cli-plugins/docker-buildx"
chmod +x "$HOME/.docker/cli-plugins/docker-buildx"
```

If `docker.service` still fails to enable with "Unit file docker.service does
not exist", the package install above did not complete — rerun it and check
for errors before continuing. Reconnect after the `usermod` command so the
Docker group membership applies, then verify:

```bash
docker version
docker compose version
docker buildx version
```

### 4.4 Clone Repository
```bash
sudo mkdir -p /opt/hub1z
sudo chown -R ec2-user:ec2-user /opt/hub1z
git clone https://github.com/<YOUR_ORG>/hub1z-app.git /opt/hub1z
cd /opt/hub1z
```

### 4.5 Set Up SSH Key for GitHub (on EC2)
To avoid entering credentials on every `git pull`:
```bash
ssh-keygen -t ed25519 -C "hub1z-ec2" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```
Add the public key as a **read-only deploy key** in the repository's
Settings > Deploy keys, not an account-wide key, then switch the remote:
```bash
cd /opt/hub1z
git remote set-url origin git@github.com:<YOUR_ORG>/hub1z-app.git
ssh -T git@github.com  # Should greet you by username
```

### 4.6 Set Up Environment
```bash
cp .env.example .env
nano .env
```
The base Compose file constructs a local PostgreSQL URL from `POSTGRES_*`.
Production RDS requires the override in section 4.10; adding `DATABASE_URL`
to `.env` alone will NOT switch either app service to RDS. Start with:
```env
FLASK_ENV=production
APP_NAME=hub1z
# Docker Compose runs Gunicorn on port 8000 (not the Flask dev-server default
# of 5000). Use the EC2 public IP/DNS with :8000 until Nginx is configured in
# section 5, then drop the port once Nginx proxies port 80/443 to 8000.
APP_BASE_URL=http://<EC2_PUBLIC_DNS_OR_DOMAIN>:8000
SECRET_KEY=<LONG_RANDOM_SECRET>
PLATFORM_BASE_DOMAIN=hub1z.com
DEPLOY_MODE=shared
OPERATOR_TRIAL_DAYS=14

POSTGRES_USER=hub1z
POSTGRES_PASSWORD=<LONG_RANDOM_DATABASE_PASSWORD>
POSTGRES_DB=hub1z
POSTGRES_PORT=5433

STORAGE_BACKEND=s3
AWS_REGION=ap-south-1
AWS_S3_PLATFORM_BUCKET=hub1z-platform-documents-<ACCOUNT_ID>
AWS_S3_OPERATOR_BUCKET=hub1z-operator-documents-<ACCOUNT_ID>
AWS_S3_URL_TTL=3600

# Configure these after SES domain/sender verification in section 6.
MAIL_SERVER=email-smtp.ap-south-1.amazonaws.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=<SES_SMTP_USERNAME>
MAIL_PASSWORD=<SES_SMTP_PASSWORD>
MAIL_DEFAULT_SENDER=no-reply@hub1z.com
MAIL_SUPPRESS_SEND=false

BOOKING_MIN_ADVANCE_MINUTES=15
BOOKING_MAX_ADVANCE_DAYS=60
BOOKING_CANCEL_WINDOW_MINUTES=60
DEFAULT_ROOM_SLOT_MINUTES=30
TIMEZONE=Asia/Kolkata

# Fresh installs seed only the platform owner; operator credentials are supplied
# explicitly when an operator is provisioned.
SEED_DEMO=false
MARKETPLACE_ENABLED=false
# Empty means deliver to actual recipients, not the Compose default test mailbox.
MAIL_REDIRECT_TO=
MAIL_REDIRECT_KEEP_DOMAINS=
```
For the new dev VM, use `APP_BASE_URL=https://dev.hub1z.com`,
`PLATFORM_BASE_DOMAIN=dev.hub1z.com`, a different `SECRET_KEY`, different
database credentials and dedicated dev buckets. Keep `MAIL_SUPPRESS_SEND=true`
unless explicitly testing mail; then redirect ALL mail to your test mailbox
with `MAIL_REDIRECT_TO=<YOUR_TEST_EMAIL>` and `MAIL_REDIRECT_KEEP_DOMAINS=`.
Never copy the production `.env`. Run `chmod 600 .env`.
Do not set `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` on EC2 when the
instance role from section 4 has S3 permissions. Never commit `.env` or place
secrets directly in the repository.

### 4.7 Start the Application
This section starts the **local-database dev stack**. On production, complete
section 4.10 and use its two-file Compose commands instead.
Before starting the base Compose stack on dev, correct its `db` healthcheck:
it currently hardcodes `coworkhub`. Use
`pg_isready -U "$${POSTGRES_USER}" -d "$${POSTGRES_DB}"` in the Compose
healthcheck instead. Bind the web port as `127.0.0.1:8000:8000` and remove the
`db` port publication entirely (containers use `db:5432` internally).
These are required Compose changes, not settings `.env` can apply.

```bash
docker compose up --build -d
```
This builds and starts the `web` and `db` containers, applies database
migrations, and (only when `SEED_DEMO=true`) seeds demo data — leave
`SEED_DEMO=false` on dev/prod servers you intend to use for real operators.

### 4.8 Create the Platform Owner and (Optionally) an Operator
With `SEED_DEMO=false`, the startup command does not run `seed-demo` or
automatically create a platform owner. On a fresh dev/RDS database, create
one explicitly with a unique strong password (never the Compose default).
Do not create a duplicate if restoring the existing production database:
```bash
docker compose exec web flask --app wsgi.py create-admin \
  --email you@hub1z.com --password '<STRONG_PASSWORD>' --platform-owner
```
To change the email of an existing Platform Owner (e.g. after renaming
`PLATFORM_OWNER_EMAIL` in `.env`), rename the account in place instead of
creating a duplicate:
```bash
docker compose exec web flask --app wsgi.py update-platform-owner-email \
  --old-email platform@hub1z.com --new-email admin@hub1z.com
```
Provision an operator directly from the CLI, or invite/provision one
later from `/platform/` in the browser:
```bash
docker compose exec web flask --app wsgi.py create-operator \
  --slug my-space --name "My Space" \
  --primary-domain my-space.hub1z.com \
  --admin-email admin@my-space.example --admin-password '<STRONG_PASSWORD>'
```

### 4.9 Verify
```bash
docker compose ps
docker compose logs -f web
curl -f http://localhost:8000/healthz
```
- App (before Nginx/SSL): `http://<public-ip>:8000`
- Admin login: `http://<public-ip>:8000/auth/login`
- Platform dashboard: `http://<public-ip>:8000/platform/`

Use these IP URLs only through a restricted connection before DNS setup.
For normal access, use the correct platform hostname; operator logins require
their workspace hostname. `/healthz` alone does not prove RDS is reachable.

### 4.10 Production RDS and Database Cutover

#### Create RDS in the AWS Console
1. RDS > Subnet groups: create `hub1z-prod-db-subnets` using both private
  subnets in the **current production EC2 VPC**.
2. RDS > Create database > Standard create > **PostgreSQL**, not Aurora.
  Choose a supported PostgreSQL major compatible with the current PostgreSQL
  16 source; avoid a version already subject to Extended Support charges.
3. Identifier: `hub1z-prod-db`; initial database: `hub1z`. Use a strong master
  credential; create a separate application DB login with schema/DDL privileges
  for Alembic. Do not use the master login for routine app traffic.
4. Start with an available `db.t4g.micro`/`db.t4g.small` and gp3 storage at the
  engine's allowed minimum (typically 20 GiB). Set a storage autoscaling cap.
  Single-AZ is the budget option; Multi-AZ provides failover at added cost.
5. Connectivity: current VPC, `hub1z-prod-db-subnets`, public access **No**,
  security group **`hub1z-prod-rds-sg` only**. Port **5432**, not Compose's 5433.
6. Enable storage encryption, deletion protection, automatic backups (7-14 days),
  and a maintenance window outside busy hours. Enable PostgreSQL log export
  with an explicit CloudWatch retention period. Set/confirm `rds.force_ssl=1`.
7. Note the endpoint once Available. Dev must never use this endpoint or login.

#### Compose RDS Override (Both Web and Scheduler)
The repository's [compose.rds.yml](../compose.rds.yml) is the production override.
It needs Docker Compose **2.24.4+** (for `!override` and `!reset`). It stops the
local `db` container, takes `DATABASE_URL` from the protected `.env`, binds port
8000 to localhost only, mounts the RDS CA bundle, and forces `SEED_DEMO=false`
so Compose's default of `true` can never insert demo operators into production.

Download the RDS CA bundle and make it readable by the container's `app` user:

```bash
mkdir -p certs
curl -fL https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
  -o certs/global-bundle.pem
chmod 755 certs
chmod 644 certs/global-bundle.pem
```

Add to production `.env` (percent-encode reserved characters in the username
and password; quote the value so Compose does not interpret password `$` signs):

```env
DATABASE_URL='postgresql+psycopg2://hub1z_app:<URL_ENCODED_PASSWORD>@<RDS_ENDPOINT>:5432/hub1z?sslmode=verify-full&sslrootcert=/app/certs/global-bundle.pem'
SEED_DEMO=false
MARKETPLACE_ENABLED=false
```

Always include both files for production commands. Check the resolved model
without printing secrets:

```bash
docker compose -f docker-compose.yml -f compose.rds.yml config --quiet
```

#### Choose Fresh Database or Restore Existing Data
For an intentionally empty production database, create the application login
and grant ownership of the `hub1z` database and rights to its `public` schema,
then run Alembic and create the platform owner. Do not import test data by accident.

For a database named `hub1z`, connect as the RDS master using an SSL-verified
`psql` session and run (the password prompt is interactive, not logged SQL):

```sql
CREATE ROLE hub1z_app LOGIN;
\password hub1z_app
ALTER DATABASE hub1z OWNER TO hub1z_app;
\connect hub1z
GRANT USAGE, CREATE ON SCHEMA public TO hub1z_app;
```

Keep the master credentials separate. For a restore, use `hub1z_app` as the
restore login so it owns the restored tables and can run future migrations.

If preserving existing data, rehearse a restore first. During final cutover:
1. Put Nginx into maintenance mode so new writes cannot arrive, and stop
  **both** `web` and `scheduler` using the existing Compose configuration.
2. Dump the local database using PostgreSQL 16 tools:
  `docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-acl' > hub1z-cutover.sql`.
  Protect the dump with `chmod 600`; do not commit it.
3. Restore into an **empty** RDS database using `psql -v ON_ERROR_STOP=1`
  over `sslmode=verify-full`, with a client version at least as new as the
  source. Supply credentials with a protected `.pgpass` or secret mechanism,
  not command-line passwords. Restore as the application/schema owner.
4. Preserve S3 objects and the existing uploads volume; DB migration does not
  migrate documents. If switching local uploads to S3, that is a separate task.
5. Run migrations once, start web then scheduler, and verify DB-backed pages:

```bash
docker compose -f docker-compose.yml -f compose.rds.yml build web scheduler
docker compose -f docker-compose.yml -f compose.rds.yml run --rm --no-deps web flask --app wsgi.py db upgrade
docker compose -f docker-compose.yml -f compose.rds.yml up -d --wait web scheduler
docker compose -f docker-compose.yml -f compose.rds.yml exec -T web flask --app wsgi.py db current
curl -f http://127.0.0.1:8000/healthz
```

Confirm platform login, operator resolution, invoice history, document download,
and a controlled write. Confirm SSL using `pg_stat_ssl` on an application
connection. Remove maintenance mode only after verification. Stop local `db`
after cutover but retain its volume until the rollback window ends; **never run
`docker compose down -v`**. Replace the existing deploy script with commands
using the RDS override so a later deployment cannot silently revert to local DB.

Rollback before accepting new writes: stop web/scheduler, return to the original
database configuration and restart them. After RDS has accepted writes, do not
simply switch back: reconcile/export those writes first to avoid data loss.

## 5. Domain and SSL Setup

Hub1z resolves the operator from the `Host` header
(`DEPLOY_MODE=shared`), so every operator subdomain
(`<operator-slug>.hub1z.com`) must resolve to the same instance and must be
covered by the TLS certificate. This means a **wildcard certificate** is
required, not just the apex and `www`.

### 5.0 Nginx for IP-Only Access (No Domain Yet)

If `hub1z.com` isn't pointed at this instance yet, use this interim step to
put Nginx in front of the app on the EC2 public/Elastic IP now, then swap in
the wildcard `hub1z.com` server block from section 5.5 once DNS is ready.
Let's Encrypt cannot issue a certificate for a bare IP address, so this step
is HTTP-only.
```bash
sudo dnf install -y nginx
sudo nano /etc/nginx/conf.d/hub1z.conf
```
```nginx
server {
    listen 80;
    server_name 43.204.37.219;  # replace with this instance's public/Elastic IP

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
```bash
sudo nginx -t
sudo systemctl enable --now nginx
```
Update `.env` so `APP_BASE_URL` matches the public port Nginx now serves
(80), not the internal container port (8000):
```env
APP_BASE_URL=http://43.204.37.219
```
```bash
docker compose up -d
```
Open `http://43.204.37.219/auth/login` — no `:8000` needed once Nginx is
listening on port 80.

### 5.1 Route 53 Hosted Zone
1. Route 53 > Hosted zones > Create hosted zone
2. Domain name: `hub1z.com` (Public hosted zone)
3. Note the 4 NS records

### 5.2 Update Nameservers at Registrar
1. Registrar → Domain List → `hub1z.com` → Nameservers → Custom DNS
2. Enter the 4 Route 53 NS values (without trailing dots)

### 5.3 Create DNS Records in Route 53
| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | *(blank)* | `<ELASTIC_IP>` | 300 |
| A | `*` | `<ELASTIC_IP>` | 300 |
| A | `dev` | `<DEV_ELASTIC_IP>` | 300 |
| A | `*.dev` | `<DEV_ELASTIC_IP>` | 300 |
| MX/TXT | *(blank)* | your mail provider's records, if any | 300 |

> The wildcard `A` record is what makes `<operator-slug>.hub1z.com` resolve
> without a DNS change per operator. Add SES DKIM CNAME records via
> **SES → Identities → Publish DNS records to Route53** in section 6.

Allocate and associate an Elastic IP with the instance first so the DNS
records above don't need to change on every reboot.

Retain the existing hosted zone and its records; do not replace nameservers.
The explicit `dev` and `*.dev` records separate dev from production's `*`.
On dev, use `server_name dev.hub1z.com *.dev.hub1z.com` in Nginx and request
a separate certificate with `-d dev.hub1z.com -d '*.dev.hub1z.com'`.
Production's `*.hub1z.com` certificate does **not** cover `foo.dev.hub1z.com`.
Use `/etc/letsencrypt/live/dev.hub1z.com/` certificate paths on dev.

### 5.4 Install Nginx
```bash
sudo dnf install -y nginx
```

### 5.5 Configure Nginx
```bash
sudo nano /etc/nginx/conf.d/hub1z.conf
```
```nginx
server {
    listen 80;
    server_name hub1z.com *.hub1z.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
`proxy_set_header Host $host` is required — Hub1z's operator resolver depends
on the original `Host` header to route each operator subdomain.

Validate and start:
```bash
sudo nginx -t
sudo systemctl enable --now nginx
```

### 5.6 Wildcard SSL with Let's Encrypt
A wildcard certificate needs DNS-01 validation, so use the Route 53 Certbot
plugin instead of the `--nginx` HTTP-01 flow. This requires the EC2 instance
to have an IAM role with Route 53 permissions — `certbot` reads credentials
from the instance metadata service, not from `aws configure`.

Check whether the instance already has a role attached:
```bash
TOKEN=$(curl -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
  http://169.254.169.254/latest/api/token)
curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/iam/security-credentials/
```
A 404 for the role path indicates no role; a 401 without a token does not.
Create/attach a role if needed:

1. **IAM → Roles → Create role**
   - Trusted entity type: `AWS service`
   - Use case: `EC2` → Next
   - Skip attaching managed policies for now → Next
   - Role name: `hub1z-ec2-role` → Create role
   - (If the instance already has a role from section 6.4/7.2, reuse it —
     skip to step 2 and add the inline policy below to that existing role.)
2. Open the role → **Add permissions → Create inline policy → JSON tab**,
   paste (replace `<HOSTED_ZONE_ID>` with the ID from **Route 53 → Hosted
   zones → hub1z.com**, shown as `Z0123456ABCDEFG`):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "Hub1zRoute53Certbot",
         "Effect": "Allow",
         "Action": "route53:ChangeResourceRecordSets",
         "Resource": "arn:aws:route53:::hostedzone/<HOSTED_ZONE_ID>"
       },
       {
         "Sid": "Hub1zRoute53ListAndGetChange",
         "Effect": "Allow",
         "Action": ["route53:ListHostedZones", "route53:GetChange"],
         "Resource": "*"
       }
     ]
   }
   ```
   Name it `hub1z-route53-certbot` → Create policy
3. **EC2 → Instances → select the instance → Actions → Security → Modify
   IAM role**, choose `hub1z-ec2-role`, **Update IAM role**
4. Re-run the check from above — it should now list a role name instead of
   an empty response. Wait a few seconds for the metadata cache to refresh,
   then retry certbot.

```bash
sudo dnf install -y certbot python3-certbot-dns-route53
sudo certbot certonly --dns-route53 \
  -d hub1z.com -d '*.hub1z.com' \
  --non-interactive --agree-tos -m admin@hub1z.com
```

Point Nginx at the issued certificate:
```nginx
server {
    listen 443 ssl;
    server_name hub1z.com *.hub1z.com;

    ssl_certificate     /etc/letsencrypt/live/hub1z.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/hub1z.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
server {
    listen 80;
    server_name hub1z.com *.hub1z.com;
    return 301 https://$host$request_uri;
}
```
```bash
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable --now certbot-renew.timer
```
Set `APP_BASE_URL=https://hub1z.com` in `.env` and restart the web container
after this step. Certificates auto-renew every ~60 days, free via Let's Encrypt.

## 6. AWS SES Email Setup

New AWS accounts start in **SES Sandbox mode** — you can only send to
verified addresses.

### 6.1 Verify Sending Domain
1. AWS Console → SES → Identities → Create identity
2. Identity type: Domain
3. Domain: `hub1z.com`
4. Enable Easy DKIM (RSA 2048-bit)
5. Create identity
6. Add the 3 CNAME records SES provides into Route 53 → `hub1z.com`
7. Wait 10–30 min for verification (status → Verified)

### 6.2 Verify Sender Email (Sandbox)
1. SES → Identities → Create identity
2. Identity type: Email address
3. Enter: `no-reply@hub1z.com`
4. Click the verification link in your inbox

### 6.3 Verify Recipient Emails (Sandbox only)
While in sandbox, verify any email addresses you want to send to (your own
test accounts, early operator admins, etc.) the same way.

### 6.4 Credentials for SES
The current app uses Flask-Mail **SMTP**, not the SES API. Attaching
`ses:SendEmail` to the EC2 role does not authenticate SMTP. Use SES SMTP
credentials, preferably stored through the app's `MAIL_CREDENTIALS_SECRET_NAME`
AWS Secrets Manager integration (grant only `secretsmanager:GetSecretValue`
for that secret, and KMS decrypt if using a customer-managed key). Otherwise
store SMTP credentials in the protected `.env`. Create them under
**SES → SMTP settings → Create SMTP credentials** and set:
```env
MAIL_SERVER=email-smtp.ap-south-1.amazonaws.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=<SES_SMTP_USERNAME>
MAIL_PASSWORD=<SES_SMTP_PASSWORD>
MAIL_DEFAULT_SENDER=no-reply@hub1z.com
```

### 6.5 Bounce and Complaint Notifications
AWS expects a working bounce/complaint process before granting production
access. Use two separate SNS topics (one for bounces, one for complaints)
that both email `support@hub1z.com` — this mirrors the pattern AWS has
already approved for other properties we run. SES's built-in account-level
suppression list (on by default) already stops future sends to
bouncing/complaining addresses automatically, so this step is about
visibility/monitoring for your team, not suppression itself.

1. **SNS → Topics → Create topic** (repeat for both):
   - Type: Standard
   - Name: `ses-bounces-hub1z` → Create topic
   - Name: `ses-complaints-hub1z` → Create topic
2. Open each topic → **Create subscription**
   - Protocol: Email
   - Endpoint: `support@hub1z.com`
   - Create subscription, then click the confirmation link AWS emails to
     `support@hub1z.com` (one link per topic — confirm both)
3. **SES → Identities → hub1z.com → Notifications** tab
   - Bounce feedback → Edit → SNS topic: `ses-bounces-hub1z` → Save
   - Complaint feedback → Edit → SNS topic: `ses-complaints-hub1z` → Save
   - (Leave "Delivery" notifications off — high volume, low value)
4. Send a test email and confirm `support@hub1z.com` is subscribed and
   confirmed on both topics; use the SES mailbox simulator
   (`bounce@simulator.amazonses.com`, `complaint@simulator.amazonses.com`)
   to verify a notification actually arrives on each topic before relying
   on it.
5. Note both topic ARNs (`arn:aws:sns:ap-south-1:<ACCOUNT_ID>:ses-bounces-hub1z`,
   `arn:aws:sns:ap-south-1:<ACCOUNT_ID>:ses-complaints-hub1z`) — AWS support
   requests for production access typically ask you to state these
   explicitly.

This satisfies AWS's requirement to describe bounce/complaint handling in
the production-access request: SES suppresses the address automatically,
and `support@hub1z.com` receives a copy of every bounce/complaint so a
human can follow up (e.g. correct a typo'd address, or investigate a
pattern of complaints).

### 6.6 Request Production Access
1. SES → Account dashboard → Request production access
2. Mail type: Transactional
3. Website URL: `https://hub1z.com`
4. Use case: describe transactional emails for signup, invites, invoices, and password resets; note expected low daily volume
5. Mention the bounce/complaint handling from section 6.5 if asked to elaborate
6. AWS typically approves within 24 hours

### 6.7 Update `.env` and Restart
```env
MAIL_SUPPRESS_SEND=false
```
```bash
docker compose up -d --force-recreate web scheduler
```
For production RDS, include `-f docker-compose.yml -f compose.rds.yml`.
Keep production `MAIL_REDIRECT_TO=` empty; use suppression/redirection on dev.

## 7. S3 Storage for Documents

S3 stores platform-owned files and operator-owned files (KYC, contracts,
invoices, floor maps, expense receipts) in two separate private buckets.

### 7.1 Create the Buckets
1. Go to AWS Console → S3 → Create bucket
2. Repeat for both:
   - `hub1z-platform-documents-<ACCOUNT_ID>`
   - `hub1z-operator-documents-<ACCOUNT_ID>`
3. Region: Asia Pacific (Mumbai) `ap-south-1`
4. Block Public Access settings: check **Block all public access** (all 4 sub-options)
5. Default encryption: Server-side encryption with Amazon S3 managed keys (SSE-S3).
  Bucket Keys apply to SSE-KMS, not SSE-S3.
6. Enable versioning
7. Leave everything else as defaults and create

For dev create two additional buckets with `-dev` names and a separate EC2
role that can access only those buckets. Reuse the actual production bucket
names already configured; do not rename them or assume their names match scope.
Require IMDSv2 on both EC2 instances. Docker needs access to the instance role;
if credentials cannot be obtained from containers, configure the metadata
response hop limit appropriately (commonly 2 for a bridged Docker network).

### 7.2 IAM Policy for S3 Access
Attach an inline policy to the EC2 instance role (preferred) or a dedicated
IAM user:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Hub1zPlatformDocs",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::hub1z-platform-documents-<ACCOUNT_ID>/platform/*"
    },
    {
      "Sid": "Hub1zOperatorDocs",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::hub1z-operator-documents-<ACCOUNT_ID>/operators/*"
    },
    {
      "Sid": "Hub1zListBuckets",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": [
        "arn:aws:s3:::hub1z-platform-documents-<ACCOUNT_ID>",
        "arn:aws:s3:::hub1z-operator-documents-<ACCOUNT_ID>"
      ]
    }
  ]
}
```
Name it `Hub1zS3DocumentAccess`. Do not attach `AdministratorAccess` or
broaden the resource beyond the two bucket prefixes above.

### 7.3 Environment Variables
Already set in section 4.6:
```env
STORAGE_BACKEND=s3
AWS_REGION=ap-south-1
AWS_S3_PLATFORM_BUCKET=hub1z-platform-documents-<ACCOUNT_ID>
AWS_S3_OPERATOR_BUCKET=hub1z-operator-documents-<ACCOUNT_ID>
AWS_S3_URL_TTL=3600
```

### 7.4 Bucket Structure
```
platform/documents/...                              — platform-owned files
operators/{operator_id}/documents/...                — operator workspace documents
operators/{operator_id}/companies/{company_id}/...   — company KYC, contracts, addenda
operators/{operator_id}/expenses/...                 — expense receipts
```

### 7.5 Security Notes
- No public access: Block Public Access is enabled on both buckets
- Server-side encryption: objects are encrypted at rest with SSE-S3
- Presigned URLs: document downloads use time-limited presigned URLs (`AWS_S3_URL_TTL`, default 1 hour)
- IAM scoping: the policy only grants access to the `platform/*` and `operators/*` prefixes on their respective buckets
- File type restriction: uploads only accept `pdf, png, jpg, jpeg, docx, xlsx` (receipts: `pdf, png, jpg, jpeg`)

### 7.6 Apply Migration
After deploying, make sure the document-ownership migration has run:
```bash
cd /opt/hub1z
docker compose exec web flask --app wsgi.py db upgrade
```

## 8. Monitoring and Security
- Enable CloudWatch monitoring on both instances
- Set up CloudWatch alarms for CPU, status checks, memory and disk space.
  Memory/disk require the CloudWatch Agent; basic EC2 metrics do not include them.
  For RDS monitor FreeStorageSpace, FreeableMemory, CPU and DatabaseConnections.
- Regularly update packages (`sudo dnf update -y`)
- Use AWS Systems Manager for patch management and shell access instead of open SSH where possible
- Keep the security groups minimal: only Nginx-fronted 80/443 public, no direct public access to 5432/5433 or (on prod) 8000
- Consider AWS WAF in front of Nginx/ALB once traffic volume justifies it

## 9. Backup and Recovery

### 9.1 PostgreSQL Logical Backups
For production RDS, enable automated backups/PITR and take a manual snapshot
before migrations. Regularly test restoration to a **separate** private DB;
backups do not replace restore testing. Retain a final snapshot on intentional deletion.
For dev local PostgreSQL (or an optional additional logical backup), use:
```bash
mkdir -p /opt/hub1z/backups
DATE=$(date -u +%Y-%m-%dT%H-%M-%SZ)
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  | gzip > "/opt/hub1z/backups/hub1z-$DATE.sql.gz"
aws s3 cp "/opt/hub1z/backups/hub1z-$DATE.sql.gz" \
  "s3://<DEV_BACKUP_BUCKET>/backups/postgres/hub1z-$DATE.sql.gz"
```
The S3 policy in section 7.2 allows only `operators/*` and `platform/*`, NOT
`backups/*`. Grant a separate role-scoped PutObject permission for the backup
prefix/bucket, install AWS CLI before this command, and set retention/lifecycle
rules. Do not place dev backups in the production document buckets.
Schedule this with cron or a systemd timer. Keep multiple backup generations
and periodically test restoring into a separate database.

### 9.2 EC2/EBS Snapshots
Set up automated EBS snapshots for both instances as a secondary safety net.
A filesystem snapshot alone is not a substitute for the PostgreSQL-aware
`pg_dump` backup above — use both.

## 10. Optional: CI/CD (Future Work)
This repository does not yet include a CI/CD pipeline. If you want the same
workflow described in project templates elsewhere — any branch push
auto-deploys to dev, and a push to `main` deploys to prod behind a manual
approval gate — add a GitHub Actions workflow that SSHes into the target
instance and runs:
```bash
cd /opt/hub1z && git pull --ff-only && \
  docker compose -f docker-compose.yml -f compose.rds.yml up --build -d --wait web scheduler
```
The web startup already applies Alembic migrations before Gunicorn; avoid
also running an unnecessary second upgrade after startup. Use the base Compose
file for dev. Do not auto-deploy arbitrary branches concurrently to one dev DB:
select a dev branch or serialize deployments. Keep production approval explicit.
Store `DEV_HOST`/`DEV_SSH_KEY` and `PROD_HOST`/`PROD_SSH_KEY` as GitHub
Actions secrets, and gate the `main` branch deploy with a `production`
GitHub Environment that requires a reviewer, mirroring the dev/prod split
already established in sections 2–4.

## Troubleshooting
- Check Docker logs: `docker compose logs -f web` / `docker compose logs -f db`
- Nginx logs: `sudo tail -f /var/log/nginx/error.log`
- Certbot renewal dry run: `sudo certbot renew --dry-run`
- Health check: `curl -f http://localhost:8000/healthz`
- Firewall: ensure security groups allow the necessary traffic and nothing more
- Operator subdomain not resolving: confirm the wildcard `A` record and that Nginx forwards the original `Host` header
