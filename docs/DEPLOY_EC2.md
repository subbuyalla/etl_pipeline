# Deploy on EC2 with Docker + RDS

Step-by-step guide for production: **EC2 runs API + poller**, **RDS holds metadata**.

## Architecture

```
Internet / dbt webhooks
        │
        ▼
   EC2 (t3.small+)
   ├── api      :8002
   └── poller   (sync every 5 min)
        │
        ▼
   RDS MySQL 8.0  (database: metadata)
```

Tool credentials (dbt, Snowflake) are stored via `POST /v1/tools` after deploy — not in the Docker image.

---

## 1. AWS setup

### EC2

| Setting | Value |
|---------|--------|
| AMI | Ubuntu 22.04 LTS |
| Instance | **t3.small** (2 GB RAM) minimum |
| Storage | 20–30 GB gp3 |
| Security group inbound | TCP **8002** from your IP (or 443 if using nginx) |
| Security group outbound | All (needs HTTPS to dbt Cloud, Snowflake, etc.) |

Optional: attach an **Elastic IP** for a stable webhook URL.

### RDS MySQL

| Setting | Value |
|---------|--------|
| Engine | MySQL 8.0 |
| Instance | db.t3.micro or db.t4g.micro |
| DB name | `metadata` |
| Security group | Allow **3306** from EC2 security group |

Note the RDS endpoint, e.g. `database-1.xxxxx.eu-north-1.rds.amazonaws.com`.

---

## 2. Install Docker on EC2

SSH into the instance:

```bash
ssh -i your-key.pem ubuntu@<ec2-public-ip>
```

Install Docker:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER
```

Log out and back in so `docker` works without sudo.

Verify:

```bash
docker --version
docker compose version
```

---

## 3. Clone the repo

```bash
git clone https://github.com/subbuyalla/etl_pipeline.git
cd etl_pipeline
git checkout subbu   # or your branch
```

---

## 4. Create `.env` on EC2

**Never commit `.env` to git.** Create it on the server only:

```bash
cp .env.example .env
nano .env
```

Minimum production values:

```env
# RDS connection (preferred — overrides compose DB_HOST)
DATABASE_URL=mysql+pymysql://USER:PASSWORD@your-rds-endpoint.rds.amazonaws.com:3306/metadata

# Encrypt tool secrets stored in obs_secrets
SECRETS_MASTER_KEY=<generate-on-server>

TENANT_ID=demo

# Public URL for webhooks (use Elastic IP or domain)
PUBLIC_BASE_URL=http://<ec2-public-ip>:8002

# Poller
SYNC_INTERVAL_SECONDS=300
RAW_RETENTION_DAYS=30
```

Generate Fernet key on EC2:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the output into `SECRETS_MASTER_KEY`.

---

## 5. Start the stack

Use the **production compose file** (no local MySQL container):

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Check status:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f api
```

---

## 6. Verify

From EC2:

```bash
curl -s http://127.0.0.1:8002/health | python3 -m json.tool
curl -s http://127.0.0.1:8002/api/v1/health | python3 -m json.tool
```

From your laptop:

- Docs: `http://<ec2-public-ip>:8002/docs`
- Overview: `http://<ec2-public-ip>:8002/api/v1/overview`

Tables are created automatically on first request (`ensure_tables`).

---

## 7. Configure tools and pipeline (API)

Open `http://<ec2-public-ip>:8002/docs` and run:

### 7a. Create tools

1. **Source DB** — `POST /v1/tools` (kind: database, connector: snowflake/postgres/…)
2. **Target DB** — `POST /v1/tools`
3. **ETL** — `POST /v1/tools` (kind: etl, connector: dbt)

Store secrets via `POST /v1/tools/{tool_id}/secret` (encrypted with `SECRETS_MASTER_KEY`).

Test each tool: `POST /v1/tools/{tool_id}/test`

### 7b. Create pipeline

```http
POST /v1/pipelines/from-tools
{
  "pipeline_name": "ecommerce_etl",
  "source_tool_ids": ["<source-tool-id>"],
  "etl_tool_id": "<dbt-tool-id>",
  "target_tool_ids": ["<target-tool-id>"]
}
```

### 7c. First sync

```http
POST /v1/sync
{
  "pipeline_id": "<pipeline-id>"
}
```

Or wait for the poller (every 5 minutes).

---

## 8. dbt webhooks (optional)

Point dbt Cloud webhooks to:

```
http://<ec2-public-ip>:8002/webhooks/dbt/<pipeline_name>
```

Set `PUBLIC_BASE_URL` in `.env` to the same base URL so `/health` returns correct webhook URLs.

For production, put **nginx + HTTPS** in front and use `https://your-domain/webhooks/dbt/...`.

---

## 9. Operations

### View logs

```bash
docker compose -f docker-compose.prod.yml logs -f api poller
```

### Restart after `.env` change

```bash
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d
```

### Update code

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

### Demo data (optional smoke test)

```bash
docker compose -f docker-compose.prod.yml exec api python scripts/seed_demo_metadata.py
```

---

## 10. Security checklist

- [ ] `.env` only on EC2, never in git
- [ ] RDS not publicly accessible (EC2 SG only)
- [ ] EC2 port 8002 restricted to trusted IPs (or use ALB + HTTPS)
- [ ] `SECRETS_MASTER_KEY` backed up securely
- [ ] Tool passwords via `/v1/tools/{id}/secret`, not plain `config_json`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| API can't reach RDS | Check RDS SG allows EC2 on 3306; verify `DATABASE_URL` |
| `Access denied` MySQL | Wrong user/password in `DATABASE_URL` |
| Poller not syncing | `docker compose logs poller`; check dbt/Snowflake tool secrets |
| Webhooks wrong URL | Set `PUBLIC_BASE_URL` in `.env` and restart |
| Out of memory | Upgrade to t3.small or t3.medium |

---

## Related docs

- [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md)
- [CONNECTORS.md](CONNECTORS.md)
- [DASHBOARD_API.md](DASHBOARD_API.md)
