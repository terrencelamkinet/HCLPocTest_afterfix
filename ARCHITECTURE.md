# NEXUS CRM v2 — Architecture & Compliance Core Rules

## 核心原則：SOC 2 根基開發

NEXUS CRM 從架構層面以 **SOC 2** 合規為設計目標。
所有功能開發必須符合以下六大 Control Categories：

### 🔐 Security (Common Criteria)
- **Access Control**: 所有非 public endpoint 強制 JWT authentication (RS256)
- **Encryption**: TLS 1.3 for all external traffic (Cloudflare tunnel)
- **Authentication**: 雙因素 (password + OTP for WhatsApp binding)
- **Logging**: 所有 webhook 請求記錄到 audit log
- **最小權限**: API endpoint 按 tenant 隔離，webhook 只查 wa_id

### ⏱ Availability
- Cloudflare tunnel for zero-downtime HTTPS
- Uvicorn reload for dev, Gunicorn + systemd for prod
- Health endpoint: `/api/v1/ai/health`

### 🔄 Processing Integrity
- Webhook HMAC-SHA256 signature verification (防止偽造)
- Input validation on all API endpoints
- Transaction-scoped DB operations

### 🔒 Confidentiality
- Phone numbers = PII → 必須 encryption at rest (pgcrypto)
- API keys/tokens only in `.env`, never in code
- No message content persisted to DB (only transient /tmp log)

### 👤 Privacy
- Multi-tenant RLS (38 PostgreSQL policies)
- WhatsApp mapping: wa_id 係 globally unique, 冇得 enumerate
- OTP auto-expire + used flag, never reusable
- Data retention TBD per tenant configuration

### 📋 Audit
- Webhook incoming/outgoing logged to `/tmp/whatsapp_webhook.log`
- All auth events (login, OTP, binding) trackable via activity_log table
- Placeholder for full audit trail (Phase 2)

---

## 架構決策記錄

### ADR-001: WhatsApp Integration — Security-First Design

**Status**: Accepted (2026-07-31)
**Context**: WhatsApp Cloud API + NEXUS CRM AI integration
**Decision**: All inbound webhooks verified via HMAC-SHA256.
Phone binding via OTP. No message content stored permanently.
Outbound push via template messages only.
**Consequences**:
- [+] Zero PII in permanent storage (phone numbers excluded)
- [+] Webhook forgery prevented by signature check
- [+] OTP rate limiting implemented (3/min per phone)
- [-] Access token is temporary — needs System User upgrade

### ADR-002: Multi-Tenant Isolation Strategy

**Status**: Accepted
**Decision**: PostgreSQL RLS for CRM data + application-level tenant
filtering for WhatsApp tables (which serve webhook with no auth context).
**Rationale**: WhatsApp webhook handler has no tenant context (called by Meta).
RLS would block legitimate wa_id lookups.
**Enforcement**: All auth endpoints use `get_tenant_session` + manual tenant_id filter.
Webhook handler only resolves wa_id → tenant, never exposes cross-tenant data.

### ADR-003: Rate Limiting Strategy

**Status**: Accepted (2026-07-31)
**Context**: External-facing endpoints need protection against abuse.
**Decision**: In-memory sliding-window rate limiter with 3/min limit + 5min temp ban.
Separate counters for send-otp and verify-otp to prevent correlated attacks.
**Coverage**:
- OTP Send: 3 req/min per phone → prevents SMS quota exhaustion
- OTP Verify: 3 attempts/min per phone → brute force on 6-digit OTP takes ~3.7 years
- Phone Enumeration: Same response for bound/unbound numbers → attacker can't distinguish
**Upgrade Path**: Replace with Redis-based limiter when scaling beyond single instance.

---

## Attack Defense Matrix — 對外連接

| Attack Vector | Target | Defense | Mechanism | Status |
|---------------|--------|---------|-----------|--------|
| **OTP Brute Force** | `/verify-otp` | Rate limit | 3 attempts/min → 5min ban. 6-digit OTP = 1M combos → 3.7yr to brute | ✅ |
| **OTP Flooding** | `/send-otp` | Rate limit | 3 requests/min per phone. Prevents SMS quota abuse | ✅ |
| **Phone Enumeration** | `/send-otp` | Uniform response | 200 + "sent" for both existing/new numbers. Attacker can't tell if bound | ✅ |
| **Webhook Forgery** | `/webhook` POST | HMAC-SHA256 | Meta signs with App Secret. 403 on mismatch | ✅ |
| **Webhook Replay** | `/webhook` POST | Idempotent + timestamp | Webhook handler doesn't store state → replay is harmless | ✅ |
| **Token Theft** | All auth endpoints | RS256 JWT | Asymmetric keys. Can't forge without private key | ✅ |
| **Cross-Tenant Access** | All API | Tenant isolation | `get_tenant_session` + RLS. DB-layer protection | ✅ |
| **MITM** | All traffic | TLS 1.3 | Cloudflare tunnel. No plaintext HTTP | ✅ |
| **Message Spoofing** | WhatsApp API | Bearer token | WhatsApp API requires valid access token to send | ✅ |
| **Session Hijack** | AI endpoint | Short-lived JWT | Internal bridge tokens expire in 2 minutes | ✅ |

### Attack Not Yet Covered (Phase 2)

| Attack Vector | Target | Planned Defense | Priority |
|---------------|--------|-----------------|----------|
| **Compromised Access Token** | WhatsApp API | Permanent System User token + rotation policy | 🟡 Medium |
| **DB Exfiltration** | User data | Encryption at rest (pgcrypto for PII columns) | 🟡 Medium |
| **DDoS / API Abuse** | All endpoints | IP-based rate limiting + WAF (Cloudflare) | 🟢 Low |
| **Insider Threat** | All data | Full audit trail (who accessed what, when) | 🟢 Low |

---

## SOC 2 Readiness Checklist

| Control | Status | Notes |
|---------|--------|-------|
| Access Control (CC6.1) | ✅ Implemented | JWT RS256 + RLS + rate limiting |
| Encryption in Transit (CC6.6) | ✅ Implemented | Cloudflare TLS |
| Encryption at Rest (CC6.7) | ⬜ Pending | Phone numbers, PII fields |
| Audit Logging (CC7.2) | ⚡ Partial | Webhook log + rate limit events, full trail pending |
| Change Management (CC8.1) | ⬜ Pending | CI/CD pipeline needed |
| Risk Assessment (CC3.1) | ⚡ Partial | Attack Defense Matrix documented |
| Vendor Management (CC9.1) | ⬜ Pending | Meta dependency documented |
| Incident Response (CC7.3) | ⬜ Pending | Alerting + response plan |

---

## 開發規則 (強制)

1. **所有新 API endpoint** 必須 — JWT auth + tenant isolation + input validation
2. **PII 資料** (phone, email, name) 必須標記，日後 encrypt at rest
3. **唔准 hardcode secrets** — 全部放 `.env` (already `.gitignore`)
4. **Webhook 必做 signature verification** — 唔准 bypass
5. **Rate limiting** — 每個對外 endpoint 必須有 rate limiting（OTP：3/min，其他：按場景）
6. **Anti-enumeration** — 唔好俾 attacker 知道某個 phone/email 係咪已註冊
7. **Commit message 必須註明 security impact** (如果有)
