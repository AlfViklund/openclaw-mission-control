# Security Checklist

## Authentication & Access

- [ ] `LOCAL_AUTH_TOKEN` is 50+ random characters
- [ ] `TELEGRAM_ALLOWED_USER_IDS` contains only your Telegram user ID
- [ ] Auth mode matches deployment (local for self-hosted, clerk for multi-user)
- [ ] API tokens are rotated regularly (use `/watchdog/agents/{id}/rotate-tokens`)

## Network Security

- [ ] Gateway is NOT exposed to public internet
- [ ] Use Tailscale or VPN for remote access
- [ ] CORS origins are restricted to known domains
- [ ] Database port (5432) is not exposed publicly
- [ ] Redis port (6379) is not exposed publicly

## Data Protection

- [ ] No secrets in logs or evidence files
- [ ] `.env` files are in `.gitignore`
- [ ] Artifact storage is not publicly accessible
- [ ] Evidence files are cleaned up after retention period

## OpenClaw Security

- [ ] Run `openclaw security audit` regularly
- [ ] Telegram dmPolicy is set to restrictive mode
- [ ] Allowlists are configured for all channels
- [ ] Browser control is disabled if not needed
- [ ] Permissions profiles are scoped appropriately

## Operational Security

- [ ] Regular backups of PostgreSQL database
- [ ] Token rotation schedule is documented
- [ ] Incident response plan exists
- [ ] Watchdog is monitoring all agents
- [ ] Escalation paths are configured

## Monitoring

- [ ] Health check endpoint is monitored
- [ ] Agent offline alerts are configured
- [ ] Failed run alerts are configured
- [ ] Escalation notifications reach the right person
