# CoWorkHub AWS Deployment Runbook

Step-by-step AWS setup for the CoWorkHub Flask app. This uses EC2, RDS
PostgreSQL, S3, ECR, and an Application Load Balancer.

`coworkhub` is the temporary platform identifier. It is not a public domain, so
use the ALB DNS name until a real domain is available.

## Prerequisites

- AWS account with permissions for EC2, VPC, RDS, S3, ECR, IAM, and ALB
- AWS CLI v2: `aws configure`
- Docker installed locally
- AWS region selected; examples use Mumbai: `ap-south-1`

## 0. Cost and service selection

- EC2: `t3.small` to start
- RDS: `db.t4g.small`, 20 GB gp3
- S3: private bucket for documents
- ALB: HTTP initially; add HTTPS after obtaining a domain
- ECR: private image repository
- Use SSM instead of SSH where possible

## 1. Create VPC and networking

### 1.1 Create VPC

AWS Console > **VPC > Your VPCs > Create VPC**

- Name: `coworkhub-vpc`
- IPv4 CIDR: `10.20.0.0/16`
- Enable DNS hostnames

### 1.2 Create subnets

Create four subnets in the VPC:

| Name | Availability Zone | CIDR | Use |
|---|---|---|---|
| `coworkhub-public-a` | `ap-south-1a` | `10.20.1.0/24` | EC2 / ALB |
| `coworkhub-public-b` | `ap-south-1b` | `10.20.2.0/24` | ALB |
| `coworkhub-private-a` | `ap-south-1a` | `10.20.11.0/24` | RDS |
| `coworkhub-private-b` | `ap-south-1b` | `10.20.12.0/24` | RDS |

### 1.3 Internet gateway and route table

1. Create and attach an Internet Gateway named `coworkhub-igw`.
2. Create `coworkhub-public-rt`.
3. Add `0.0.0.0/0` to the Internet Gateway.
4. Associate the route table with both public subnets.
5. Enable auto-assign public IPv4 on `coworkhub-public-a`.

Keep RDS in the private subnets. For this first setup, EC2 is public so it can
pull the image without a NAT gateway.

## 2. Security groups

### 2.1 ALB security group

Create `coworkhub-alb-sg`:

- Inbound TCP 80 from `0.0.0.0/0`
- Later add TCP 443 from `0.0.0.0/0`
- Outbound: all

### 2.2 EC2 security group

Create `coworkhub-app-sg`:

- TCP 8000 from `coworkhub-alb-sg`
- TCP 22 from your IP only, or omit SSH when using SSM
- Outbound: all

### 2.3 RDS security group

Create `coworkhub-db-sg`:

- TCP 5432 from `coworkhub-app-sg` only
- No public inbound access

## 3. Create RDS PostgreSQL

AWS Console > **RDS > Databases > Create database**

- Engine: PostgreSQL 16
- Identifier: `coworkhub-prod`
- Database: `coworkhub`
- Master username: `coworkhub`
- Generate and store a strong password
- Instance: `db.t4g.small`
- Storage: 20 GB gp3
- Public access: **No**
- VPC: `coworkhub-vpc`
- Subnet group: private subnets
- Security group: `coworkhub-db-sg`
- Backup retention: 7 days

When the database is available, copy its endpoint. The application URL is:

```text
postgresql+psycopg2://coworkhub:<DB_PASSWORD>@<RDS_ENDPOINT>:5432/coworkhub?sslmode=require
```

## 4. Create the S3 bucket

AWS Console > **S3 > Create bucket**

- Name: `coworkhub-docs-<ACCOUNT_ID>`
- Region: `ap-south-1`
- Block all public access: enabled
- Default encryption: SSE-S3
- Versioning: enabled

The app uses this bucket for contracts, KYC files, floor maps, and invoices.

## 5. Create the EC2 IAM role

### 5.1 Role

IAM > **Roles > Create role**:

- Trusted entity: EC2
- Name: `CoWorkHubAppRole`
- Attach `AmazonSSMManagedInstanceCore`

Create an instance profile named `CoWorkHubAppProfile` containing this role.

### 5.2 Application policy

Add an inline policy allowing:

- ECR image pull actions
- `s3:ListBucket` on the documents bucket
- `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on the bucket objects

Do not add public S3 access or broad `AdministratorAccess`.

## 6. Build and push the Docker image

From the repository root:

```bash
export REGION=ap-south-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws ecr create-repository --repository-name coworkhub --region $REGION
aws ecr get-login-password --region $REGION | docker login --username AWS \
  --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

docker build -t coworkhub .
docker tag coworkhub $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/coworkhub:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/coworkhub:latest
```

## 7. Launch the EC2 instance

### 7.1 Launch settings

EC2 > **Launch instance**:

- Name: `coworkhub-app`
- AMI: Amazon Linux 2023
- Instance type: `t3.small`
- VPC: `coworkhub-vpc`
- Subnet: `coworkhub-public-a`
- Auto-assign public IP: enabled
- Security group: `coworkhub-app-sg`
- IAM instance profile: `CoWorkHubAppProfile`
- Storage: 20 GB gp3

### 7.2 Install Docker

Connect with SSM or SSH and run:

```bash
sudo dnf update -y
sudo dnf install -y docker curl
sudo systemctl enable --now docker
```

### 7.3 Configure and start CoWorkHub

Set these values in the EC2 shell:

```bash
export REGION=ap-south-1
export ACCOUNT_ID=<ACCOUNT_ID>
export DB_HOST=<RDS_ENDPOINT>
export DB_PASSWORD=<DB_PASSWORD>
export S3_BUCKET=<S3_BUCKET>
export SECRET_KEY=$(openssl rand -hex 32)
export IMAGE=$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/coworkhub:latest
```

Start the container:

```bash
aws ecr get-login-password --region $REGION | docker login --username AWS \
  --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com
docker pull $IMAGE

docker run -d --restart unless-stopped --name coworkhub -p 8000:8000 \
  -e FLASK_ENV=production \
  -e APP_NAME=CoWorkHub \
  -e APP_BASE_URL=http://<ALB_DNS_NAME> \
  -e PLATFORM_BASE_DOMAIN=coworkhub \
  -e DEPLOY_MODE=shared \
  -e SECRET_KEY=$SECRET_KEY \
  -e DATABASE_URL="postgresql+psycopg2://coworkhub:$DB_PASSWORD@$DB_HOST:5432/coworkhub?sslmode=require" \
  -e STORAGE_BACKEND=s3 \
  -e AWS_REGION=$REGION \
  -e AWS_S3_BUCKET=$S3_BUCKET \
  $IMAGE

until curl -fsS http://localhost:8000/healthz; do sleep 5; done
docker exec coworkhub flask --app wsgi.py db upgrade
docker exec coworkhub flask --app wsgi.py seed-demo
```

## 8. Create the Application Load Balancer

### 8.1 Create target group

EC2 > **Target Groups > Create target group**:

- Target type: Instances
- Name: `coworkhub-tg`
- Protocol: HTTP
- Port: 8000
- Health check path: `/healthz`
- Register the `coworkhub-app` instance

### 8.2 Create load balancer

EC2 > **Load Balancers > Create Application Load Balancer**:

- Name: `coworkhub-alb`
- Scheme: Internet-facing
- Subnets: both public subnets
- Security group: `coworkhub-alb-sg`
- Listener: HTTP 80 forwarding to `coworkhub-tg`

Copy the ALB DNS name and test:

```bash
curl -f http://<ALB_DNS_NAME>/healthz
```

Open `http://<ALB_DNS_NAME>/auth/login` when the target is healthy.

## 9. First login and application setup

Seeded platform login (the SaaS operator account, lands on `/platform/`):

- Email: `platform@coworkhub.io`
- Password: `ChangeMe123!`

`seed-demo` also creates one sample tenant ("Adyar Space") with its own admin
(`admin@adyarspace.com` / `ChangeMe123!`) so you have something to click
through — a real deployment should provision real tenants from `/platform/`
and delete this sample one before onboarding customers.

Immediately change the platform password. Remove demo users and data before
onboarding real customers. Then provision real tenant(s) from `/platform/`,
and have each tenant's own admin create their locations, floors, seats,
rooms, pricing plans, companies, and staff from `/admin/`.

## 10. Domain and SSL setup later

Until a domain is available, keep using the ALB DNS name over HTTP.

When a real domain is ready:

1. Set `PLATFORM_BASE_DOMAIN` to the real domain and redeploy.
2. Create an ACM public certificate in the same AWS region.
3. Add DNS validation records at the domain registrar.
4. Add an HTTPS 443 listener to the ALB.
5. Redirect HTTP 80 to HTTPS 443.
6. Point the domain DNS record to the ALB.

Do not use `coworkhub` itself for ACM, Route 53, or SES; it is only the current
platform identifier.

## 11. AWS SES email setup later

SES requires a verified sender. After the real domain is available:

1. SES > Identities > Create identity > Domain.
2. Add the DKIM records to DNS.
3. Create SES SMTP credentials.
4. Configure the container with:

```text
MAIL_SERVER=email-smtp.ap-south-1.amazonaws.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=<SES_SMTP_USERNAME>
MAIL_PASSWORD=<SES_SMTP_PASSWORD>
MAIL_DEFAULT_SENDER=no-reply@<YOUR_DOMAIN>
```

New AWS accounts start in SES Sandbox mode. Request production access before
sending to unverified recipients.

## 12. Monitoring, backup, and troubleshooting

- Enable CloudWatch logs and EC2 monitoring.
- Keep RDS automated backups enabled.
- Test `/healthz` after every deployment.
- App logs: `docker logs -f coworkhub`
- Container status: `docker ps`
- Restart app: `docker restart coworkhub`
- Apply migrations: `docker exec coworkhub flask --app wsgi.py db upgrade`
- Check ALB target health if the site is unavailable.
- Check security groups if EC2, ALB, or RDS cannot connect.
