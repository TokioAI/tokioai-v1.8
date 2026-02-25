# 🚀 Deployment Guide

This guide covers deploying TokioAI in different environments.

## Table of Contents

- [Local Deployment](#local-deployment)
- [Docker Compose Deployment](#docker-compose-deployment)
- [GCP Cloud Deployment](#gcp-cloud-deployment)
- [Production Considerations](#production-considerations)

## Local Deployment

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Apache Kafka
- Node.js 18+

### Step 1: Database Setup

```bash
# Create PostgreSQL database
createdb soc_ai
psql soc_ai -c "CREATE USER soc_user WITH PASSWORD 'YOUR_PASSWORD';"
psql soc_ai -c "GRANT ALL PRIVILEGES ON DATABASE soc_ai TO soc_user;"
```

### Step 2: Kafka Setup

```bash
# Start Zookeeper
bin/zookeeper-server-start.sh config/zookeeper.properties

# Start Kafka
bin/kafka-server-start.sh config/server.properties

# Create topic
bin/kafka-topics.sh --create --topic waf-logs --bootstrap-server localhost:9092
```

### Step 3: Configure Environment

```bash
cp .env.example .env
# Edit .env with your configuration
nano .env
```

### Step 4: Install Dependencies

```bash
# Python dependencies
cd tokio-ai/dashboard-api
pip install -r requirements.txt

# Node.js dependencies
cd mcp-host
npm install
npm run build
```

### Step 5: Run Migrations

```bash
cd tokio-ai/dashboard-api
alembic upgrade head
```

### Step 6: Start Services

```bash
# Start dashboard API
uvicorn app:app --host 0.0.0.0 --port 8000 --reload

# In another terminal, start ML processor
cd real-time-processor
python3 kafka_streams_processor.py
```

## Docker Compose Deployment

### Quick Start

```bash
# Copy environment file
cp .env.example .env
# Edit .env with your values
nano .env

# Start all services
docker-compose up -d

# Check logs
docker-compose logs -f
```

### Services

- **PostgreSQL**: Database on port 5432
- **Kafka**: Message queue on port 9092
- **Zookeeper**: Kafka coordination on port 2181
- **Dashboard API**: Web interface on port 8000
- **ML Processor**: Real-time threat detection

### Access Services

- Dashboard: http://localhost:8000
- API Docs: http://localhost:8000/docs
- PostgreSQL: localhost:5432

## GCP Cloud Deployment

### Prerequisites

1. Google Cloud Project with billing enabled
2. gcloud CLI installed and authenticated
3. Service Account with required permissions

### Automated Deployment

```bash
./scripts/deploy-gcp.sh
```

### Manual Deployment Steps

#### 1. Create VPC Network

```bash
gcloud compute networks create tokio-vpc \
    --subnet-mode=custom \
    --bgp-routing-mode=regional
```

#### 2. Create Subnet

```bash
gcloud compute networks subnets create tokio-subnet \
    --network=tokio-vpc \
    --range=10.0.0.0/24 \
    --region=us-central1
```

#### 3. Create Firewall Rules

```bash
# Allow HTTP/HTTPS
gcloud compute firewall-rules create allow-http-https \
    --network=tokio-vpc \
    --allow tcp:80,tcp:443 \
    --source-ranges 0.0.0.0/0

# Allow SSH (restrict to your IP)
gcloud compute firewall-rules create allow-ssh \
    --network=tokio-vpc \
    --allow tcp:22 \
    --source-ranges YOUR_IP/32
```

#### 4. Create Cloud SQL Instance

```bash
gcloud sql instances create tokio-postgres \
    --database-version=POSTGRES_14 \
    --tier=db-f1-micro \
    --region=us-central1 \
    --network=tokio-vpc
```

#### 5. Create Compute Engine VM

```bash
gcloud compute instances create tokio-waf \
    --zone=us-central1-a \
    --machine-type=e2-medium \
    --network-interface=network-tier=PREMIUM,subnet=tokio-subnet \
    --image-family=cos-stable \
    --image-project=cos-cloud
```

#### 6. Deploy Application

See [DEPLOYMENT_GCP.md](DEPLOYMENT_GCP.md) for detailed Cloud Run deployment.

## Production Considerations

### Security

1. **Use HTTPS**: Configure SSL certificates (Let's Encrypt included)
2. **Private IPs**: Use Cloud SQL Private IP, not public IP
3. **Firewall Rules**: Restrict access to necessary IPs only
4. **Secrets Management**: Use GCP Secret Manager, not environment variables
5. **Authentication**: Enable strong authentication for dashboard
6. **Monitoring**: Set up Cloud Monitoring and alerting

### Performance

1. **Database**: Use appropriate Cloud SQL tier for your load
2. **Kafka**: Consider managed Kafka service for production
3. **Caching**: Implement Redis for frequently accessed data
4. **Load Balancing**: Use Cloud Load Balancer for high availability

### Backup

1. **Database**: Enable automated Cloud SQL backups
2. **Configuration**: Version control all configuration files
3. **Disaster Recovery**: Test restore procedures regularly

### Monitoring

1. **Logs**: Use Cloud Logging for centralized log management
2. **Metrics**: Set up Cloud Monitoring dashboards
3. **Alerts**: Configure alerts for critical issues
4. **Uptime**: Monitor service availability

## Troubleshooting

### Common Issues

1. **Database Connection Failed**
   - Check PostgreSQL is running
   - Verify credentials in .env
   - Check firewall rules

2. **Kafka Connection Failed**
   - Verify Kafka is running
   - Check KAFKA_BOOTSTRAP_SERVERS in .env
   - Ensure topic exists

3. **Dashboard Not Loading**
   - Check API is running
   - Verify authentication credentials
   - Check browser console for errors

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for more details.
