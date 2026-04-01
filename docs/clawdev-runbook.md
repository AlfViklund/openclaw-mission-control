# ClawDev Runbook

## Recovery Procedures

### Agent is Offline

1. Check watchdog: `POST /api/v1/watchdog/agents/{id}/wake`
2. If still offline: `POST /api/v1/watchdog/agents/{id}/reset-session`
3. If still offline: `POST /api/v1/watchdog/agents/{id}/template-sync`
4. Last resort: `POST /api/v1/watchdog/agents/{id}/rotate-tokens`

### Run is Stuck

1. Cancel: `POST /api/v1/runs/{id}/cancel`
2. Retry: `POST /api/v1/watchdog/retry-stuck-runs`
3. Check evidence: `GET /api/v1/runs/{id}/evidence`

### Pipeline is Blocked

1. Check validation: `GET /api/v1/pipeline/tasks/{id}/validate`
2. Review warnings and fix prerequisites
3. Re-execute stage: `POST /api/v1/pipeline/tasks/{id}/execute`

### Telegram Bot Not Responding

1. Check bot token in `telegram-bot/.env`
2. Verify `TELEGRAM_ALLOWED_USER_IDS` includes your user ID
3. Restart: `docker compose restart telegram-bot`

### Database Issues

1. Check health: `docker compose exec db pg_isready`
2. Restart: `docker compose restart db`
3. Backup: `docker compose exec db pg_dump -U postgres mission_control > backup.sql`
4. Restore: `docker compose exec -T db psql -U postgres mission_control < backup.sql`

### Full System Recovery

```bash
# 1. Stop everything
docker compose down

# 2. Clean restart
docker compose up -d --build --force-recreate

# 3. Verify health
curl http://localhost:8000/healthz

# 4. Run security audit
openclaw security audit

# 5. Sync all templates
python backend/scripts/sync_gateway_templates.py --gateway-id <uuid>
```

## Security Checklist

- [ ] `LOCAL_AUTH_TOKEN` is strong (50+ chars)
- [ ] `TELEGRAM_ALLOWED_USER_IDS` restricts to your user ID
- [ ] No secrets in logs or evidence files
- [ ] Gateway is not exposed to public internet
- [ ] CORS origins are restricted
- [ ] Regular token rotation schedule
- [ ] `openclaw security audit` passes
