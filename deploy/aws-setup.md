# Hub1z Webapp Deployment Runbook

This runbook provides step-by-step instructions for setting up the Hub1z Flask
webapp on AWS EC2 instances for dev and production environments.

## Prerequisites
- AWS account with appropriate permissions
- Domain: hub1z.com (owned and configured in Route 53)
- SSH key pair for EC2 access
- GitHub repository access

## 0. Cost Considerations and Service Selection
This deployment is designed for a low-to-moderate volume multi-tenant site
with affordable and secure AWS services.

- Prefer the Mumbai region (`ap-south-1`) for lower latency for India-based operators and members.
- Use `t3.micro` for dev if eligible under the free tier. For production, `t3.small` is a low-cost but reliable choice; move to `t3.medium` as operator/traffic volume grows.
- Keep PostgreSQL on the EC2 host using the existing Docker Compose `db` service, avoiding RDS costs until you need managed DB scale, multi-AZ failover, or point-in-time recovery.
- Use `gp3` EBS storage for cost-efficient persistent disk, starting with 20 GB (PostgreSQL data plus document staging live here).
- Use Nginx + Let's Encrypt (via Certbot) for free SSL instead of ACM + ALB, since Hub1z needs a wildcard certificate for `*.hub1z.com` operator subdomains.
- Use Route 53 only if the domain is already managed there; otherwise keep DNS costs minimal with an existing registrar.
- Use Security Groups and IP-restricted SSH to improve security without extra service spend.

### Estimated Chargeable Services
- EC2 t3.micro dev (free tier eligible for 12 months): $0 if within free tier, otherwise about $8–10/mo
- EC2 t3.small prod: about $15–20/mo
- EBS gp3 20 GB (per instance): about $2–3/mo
- Route 53 hosted zone: $0.50/mo plus a few cents per million DNS queries
- Elastic IP: free when attached to a running instance
- Let's Encrypt via Certbot: free public TLS certificates, including wildcard
- S3 (two document buckets, low volume): under $1–2/mo
- SES: pennies per 1,000 emails at low volume
- CloudWatch basic monitoring: free for standard EC2 metrics; logs may incur small charges if used heavily
- Data transfer: minimal for low traffic; expect under $1–5/mo for low volume

> Confirm current AWS free-tier eligibility and pricing for your account/region — the above are approximate starting-point estimates, not a quote.

> For a low-volume multi-tenant deployment, the secure and cheap configuration is: dev on `t3.micro` with a tightly scoped security group, prod on `t3.small`, Docker Compose running the app + PostgreSQL, Nginx reverse proxy with a wildcard Let's Encrypt certificate, and S3 for documents.

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
3. Create Private Subnet (reserved for a future managed database):
   - Name: `hub1z-private-subnet`
   - Availability Zone: `ap-south-1a`
   - IPv4 CIDR: `10.20.11.0/24`

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
   - Custom TCP: 8000, Source: `0.0.0.0/0` (direct dev app port, useful before Nginx is configured)

### 2.2 Prod Security Group
1. Similar to dev, but name: `hub1z-prod-sg`
2. Restrict SSH to specific IPs, or omit it and use SSM
3. No port 8000 open publicly — the app is reached only through Nginx on 80/443

In both security groups, do not open PostgreSQL ports (5432/5433) to
`0.0.0.0/0`. The web container reaches PostgreSQL over the private Docker
Compose network; no host firewall rule should expose it externally.

## 3. Launch EC2 Instances

### 3.1 Dev Instance
1. EC2 > Instances > Launch instances
2. Name: `hub1z-dev`
3. AMI: Amazon Linux 2023
4. Instance type: `t3.micro` (free tier)
5. Key pair: Select your SSH key
6. VPC: `hub1z-vpc`
7. Subnet: `hub1z-public-subnet`
8. Auto-assign public IP: Enable
9. Security group: `hub1z-dev-sg`
10. Storage: 20 GB gp3
11. Launch

### 3.2 Prod Instance
1. Same as dev, but:
   - Name: `hub1z-prod`
   - Instance type: `t3.small` (increase later if needed)
   - Security group: `hub1z-prod-sg`

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

If `docker.service` still fails to enable with "Unit file docker.service does
not exist", the package install above did not complete — rerun it and check
for errors before continuing. Reconnect after the `usermod` command so the
Docker group membership applies, then verify:

```bash
docker version
docker compose version
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
Add the public key to GitHub: [github.com/settings/keys](https://github.com/settings/keys), then switch the remote:
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
Set production values, in particular. Docker Compose constructs the internal
PostgreSQL URL from `POSTGRES_*`; do not set a host-local `DATABASE_URL` in
this deployment:
```env
FLASK_ENV=production
APP_NAME=hub1z
# Use the temporary EC2 URL until Nginx and HTTPS are configured; then change it to https://hub1z.com.
APP_BASE_URL=http://<EC2_PUBLIC_DNS_OR_DOMAIN>:8000
SECRET_KEY=<LONG_RANDOM_SECRET>
PLATFORM_BASE_DOMAIN=hub1z.com
DEPLOY_MODE=shared
TENANT_TRIAL_DAYS=14

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

# Used only if you intentionally run seed-demo=true for a demo environment.
BOOTSTRAP_ADMIN_EMAIL=admin@adyarspace.com
BOOTSTRAP_ADMIN_PASSWORD=<DEMO_ONLY_PASSWORD>
SEED_DEMO=false
```
Do not set `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` on EC2 when the
instance role from section 4 has S3 permissions. Never commit `.env` or place
secrets directly in the repository.

### 4.7 Start the Application
```bash
docker compose up --build -d
```
This builds and starts the `web` and `db` containers, applies database
migrations, and (only when `SEED_DEMO=true`) seeds demo data — leave
`SEED_DEMO=false` on dev/prod servers you intend to use for real operators.

### 4.8 Create the Platform Owner and (Optionally) a Tenant
```bash
docker compose exec web flask --app wsgi.py create-admin \
  --email you@hub1z.com --password '<STRONG_PASSWORD>' --platform-owner
```
Provision an operator/tenant directly from the CLI, or invite/provision one
later from `/platform/` in the browser:
```bash
docker compose exec web flask --app wsgi.py create-tenant \
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

## 5. Domain and SSL Setup

Hub1z resolves the tenant/operator from the `Host` header
(`DEPLOY_MODE=shared`), so every operator subdomain
(`<operator-slug>.hub1z.com`) must resolve to the same instance and must be
covered by the TLS certificate. This means a **wildcard certificate** is
required, not just the apex and `www`.

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
| MX/TXT | *(blank)* | your mail provider's records, if any | 300 |

> The wildcard `A` record is what makes `<operator-slug>.hub1z.com` resolve
> without a DNS change per operator. Add SES DKIM CNAME records via
> **SES → Identities → Publish DNS records to Route53** in section 6.

Allocate and associate an Elastic IP with the instance first so the DNS
records above don't need to change on every reboot.

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
`proxy_set_header Host $host` is required — Hub1z's tenant resolver depends
on the original `Host` header to route each operator subdomain.

Validate and start:
```bash
sudo nginx -t
sudo systemctl enable --now nginx
```

### 5.6 Wildcard SSL with Let's Encrypt
A wildcard certificate needs DNS-01 validation, so use the Route 53 Certbot
plugin instead of the `--nginx` HTTP-01 flow:
```bash
sudo dnf install -y certbot python3-certbot-dns-route53
sudo certbot certonly --dns-route53 \
  -d hub1z.com -d '*.hub1z.com' \
  --non-interactive --agree-tos -m you@hub1z.com
```
This requires the EC2 instance role (or configured AWS credentials) to have
`route53:ChangeResourceRecordSets`, `route53:GetChange`, and
`route53:ListHostedZones` permissions for the `hub1z.com` zone.

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
Prefer an IAM role attached to the EC2 instance over long-lived access keys:
EC2 → Instance → Actions → Security → Modify IAM role, then attach a policy
scoped to `ses:SendEmail` and `ses:SendRawEmail`.

If you must use SMTP credentials instead, create SES SMTP credentials under
**SES → SMTP settings → Create SMTP credentials** and set:
```env
MAIL_SERVER=email-smtp.ap-south-1.amazonaws.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=<SES_SMTP_USERNAME>
MAIL_PASSWORD=<SES_SMTP_PASSWORD>
MAIL_DEFAULT_SENDER=no-reply@hub1z.com
```

### 6.5 Request Production Access
1. SES → Account dashboard → Request production access
2. Mail type: Transactional
3. Website URL: `https://hub1z.com`
4. Use case: describe transactional emails for signup, invites, invoices, and password resets; note expected low daily volume
5. AWS typically approves within 24 hours

### 6.6 Update `.env` and Restart
```env
MAIL_SUPPRESS_SEND=false
```
```bash
docker compose down && docker compose up -d
```

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
5. Default encryption: Server-side encryption with Amazon S3 managed keys (SSE-S3), Bucket Key enabled
6. Enable versioning
7. Leave everything else as defaults and create

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
- Set up CloudWatch alarms for CPU/memory and low disk space (the EBS volume backs PostgreSQL data)
- Regularly update packages (`sudo dnf update -y`)
- Use AWS Systems Manager for patch management and shell access instead of open SSH where possible
- Keep the security groups minimal: only Nginx-fronted 80/443 public, no direct public access to 5432/5433 or (on prod) 8000
- Consider AWS WAF in front of Nginx/ALB once traffic volume justifies it

## 9. Backup and Recovery

### 9.1 PostgreSQL Logical Backups
Because PostgreSQL is not managed by RDS, backups are your responsibility.
Create a daily logical backup and copy it to S3:
```bash
mkdir -p /opt/hub1z/backups
DATE=$(date -u +%Y-%m-%dT%H-%M-%SZ)
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  | gzip > "/opt/hub1z/backups/hub1z-$DATE.sql.gz"
aws s3 cp "/opt/hub1z/backups/hub1z-$DATE.sql.gz" \
  "s3://hub1z-operator-documents-<ACCOUNT_ID>/backups/postgres/hub1z-$DATE.sql.gz"
```
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
cd /opt/hub1z && git pull && docker compose up --build -d \
  && docker compose exec -T web flask --app wsgi.py db upgrade
```
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
- Tenant/operator subdomain not resolving: confirm the wildcard `A` record and that Nginx forwards the original `Host` header
