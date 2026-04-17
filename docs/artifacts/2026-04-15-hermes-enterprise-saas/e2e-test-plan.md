# Hermes Agent Enterprise SaaS — Phase 1 MVP E2E Test Plan

| Field | Value |
|-------|-------|
| Artifact | e2e-test-plan |
| Parent | delivery-plan.md |
| Date | 2026-04-17 |
| Role | QA |
| Status | ready-for-execution |
| Scope | 30 test cases across 7 services |
| Target | Phase 1 MVP GA |

---

## 1. Test Scope & Environments

### 1.1 Scope

- **In Scope:** End-to-end happy paths + critical error paths across all Phase 1 services
- **Out of Scope:** Unit tests (per-service, already completed), load/stress testing, security penetration testing

### 1.2 Test Environments

| Environment | Infrastructure | Use Case |
|-------------|----------------|----------|
| **Local** | Docker Compose (v2) | Dev smoke testing, pre-commit |
| **Staging** | K8s (3-node cluster) | QA full regression, pre-production validation |
| **Production** | K8s (4-node cluster) | Post-deployment verification, monitoring baseline |

### 1.3 Services Under Test

| Service | Port | Role |
|---------|------|------|
| auth-service | 8001 | JWT/OIDC authentication |
| router-service | 8002 | Agent routing, session locking |
| quota-service | 8003 | Per-user quota enforcement |
| skills-registry | 8004 | Skills CRUD, hot reload |
| feishu-bot | 8005 | Feishu webhook/bot |
| admin-console | 3000 | React admin UI |
| LiteLLM proxy | 4000 | LLM gateway |

---

## 2. Test Matrix

| Test Case ID | Feature | Test Description | Priority | Service(s) | Status |
|---|---|---|---|---|---|
| E2E-001 | Auth - Mock Login | Login with dev@hermes.local / devpassword, get JWT | P0 | auth | |
| E2E-002 | Auth - Real OIDC | Click login → Keycloak redirect → callback → JWT issued | P0 | auth, keycloak | |
| E2E-003 | Auth - Token Refresh | Use refresh token to get new access token | P0 | auth | |
| E2E-004 | Auth - Invalid Login | Wrong password → 401 | P1 | auth | |
| E2E-005 | Auth - Audit Log | Login event appears in audit logs | P1 | auth | |
| E2E-006 | API Token - Create | Create hms_ token, verify Redis caching | P0 | auth | |
| E2E-007 | API Token - Use | Use token for auth-service API call | P0 | auth | |
| E2E-008 | API Token - Revoke | Revoke token → subsequent use returns 401 | P0 | auth | |
| E2E-009 | Quota - Check | Verify user quota count on first login | P0 | quota | |
| E2E-010 | Quota - Increment | Make API call → quota increments | P1 | quota, router | |
| E2E-011 | Quota - Exceeded | Exceed quota → 429 response | P0 | quota, router | |
| E2E-012 | Skills - List | GET /skills returns published skills | P0 | skills-registry | |
| E2E-013 | Skills - Create | Admin creates skill → appears in list | P0 | skills-registry | |
| E2E-014 | Skills - Update | Admin updates skill → version increments | P0 | skills-registry | |
| E2E-015 | Skills - Archive | Admin archives skill → not in public list | P0 | skills-registry | |
| E2E-016 | Skills - Hot Reload | Update skill → active pods receive reload signal | P1 | skills-registry, router | |
| E2E-017 | Router - Route Request | Send request → pod assigned → response returned | P0 | router | |
| E2E-018 | Router - Session Lock | Concurrent requests to same session → one waits | P0 | router | |
| E2E-019 | Router - Pod Pool Exhausted | All pods busy → 503 + retry after cooldown | P1 | router | |
| E2E-020 | Router - Cold Start | First request to idle pod → pod started <3s | P1 | router | |
| E2E-021 | Feishu - Webhook Receive | Send test event to /feishu/webhook → 200 | P0 | feishu-bot | |
| E2E-022 | Feishu - Message Reply | User sends message → bot replies | P0 | feishu-bot | |
| E2E-023 | Admin - User List | Admin sees paginated user list | P0 | admin-console | |
| E2E-024 | Admin - Quota Config | Admin changes user quota | P0 | admin-console | |
| E2E-025 | Admin - Audit Logs | Admin views filterable audit logs | P0 | admin-console | |
| E2E-026 | LLM - Proxy | Request routed to LiteLLM → real response | P0 | router, litellm | |
| E2E-027 | LLM - Model Fallback | Primary model fails → fallback model used | P1 | litellm | |
| E2E-028 | NAS - SQLite WAL | Pod writes to NAS → WAL works correctly | P0 | hermes-agent | |
| E2E-029 | NAS - Multi-Pod | Two pods write to same user NAS → no corruption | P0 | hermes-agent | |
| E2E-030 | OIDC - User Provisioning | First OIDC login → user created in DB | P0 | auth | |

---

## 3. Test Execution Procedures

### E2E-001: Auth - Mock Login
**Prerequisites:** Docker Compose running, auth-service healthy (`curl http://localhost:8001/health` returns 200)

**Steps:**
1. `curl -X POST http://localhost:8001/auth/login \
   -H "Content-Type: application/json" \
   -d '{"email":"dev@hermes.local","password":"devpassword"}'`
2. Verify response contains `access_token` and `refresh_token`
3. Verify token is valid: `curl http://localhost:8001/auth/me -H "Authorization: Bearer <token>"`
4. Verify response contains user info (`email`, `id`, `role`)

**Expected Result:** 200 OK, tokens returned
**Pass Criteria:** All 4 steps succeed

---

### E2E-002: Auth - Real OIDC
**Prerequisites:** Keycloak running at `http://localhost:8880`, OIDC configured in auth-service

**Steps:**
1. `curl -X GET "http://localhost:8001/auth/oidc/login?redirect_uri=http://localhost:3000/callback"`
2. Verify 302 redirect to Keycloak authorization endpoint
3. Simulate Keycloak callback: `curl -X POST "http://localhost:8001/auth/oidc/callback" -H "Content-Type: application/json" -d '{"code":"<test_code>","state":"<state>"}'`
4. Verify response contains JWT access token

**Expected Result:** 200 OK, JWT issued after OIDC flow
**Pass Criteria:** All steps succeed; token decodes correctly

---

### E2E-003: Auth - Token Refresh
**Prerequisites:** Valid refresh token from E2E-001 or E2E-002

**Steps:**
1. `curl -X POST http://localhost:8001/auth/token/refresh \
   -H "Content-Type: application/json" \
   -d '{"refresh_token":"<refresh_token>"}'`
2. Verify response contains new `access_token`
3. Verify new access token works: `curl http://localhost:8001/auth/me -H "Authorization: Bearer <new_token>"`
4. Verify old refresh token is invalidated (reuse → 401)

**Expected Result:** 200 OK, new access token returned, old refresh token invalidated
**Pass Criteria:** All 4 steps succeed

---

### E2E-004: Auth - Invalid Login
**Prerequisites:** None

**Steps:**
1. `curl -X POST http://localhost:8001/auth/login \
   -H "Content-Type: application/json" \
   -d '{"email":"dev@hermes.local","password":"wrongpassword"}'`
2. Verify HTTP 401 returned
3. Verify response body contains error message (not server stack trace)

**Expected Result:** 401 Unauthorized, safe error message
**Pass Criteria:** HTTP 401, no sensitive info leaked

---

### E2E-005: Auth - Audit Log
**Prerequisites:** Successful login from E2E-001

**Steps:**
1. After E2E-001 login succeeds, query audit log: `curl http://localhost:8001/admin/audit-logs?user_id=<user_id>&event_type=login -H "Authorization: Bearer <admin_token>"`
2. Verify entry exists with correct `event_type`, `timestamp`, `user_id`, `ip_address`

**Expected Result:** Audit log entry found with all fields populated
**Pass Criteria:** Entry exists, no missing fields

---

### E2E-006: API Token - Create
**Prerequisites:** Admin token from E2E-001 with admin role

**Steps:**
1. `curl -X POST http://localhost:8001/admin/api-tokens \
   -H "Content-Type: application/json" \
   -H "Authorization: Bearer <admin_token>" \
   -d '{"name":"e2e-test-token","scopes":["chat:write","skills:read"]}'`
2. Verify response contains `token` starting with `hms_`
3. Verify token is cached in Redis: `redis-cli GET "apitoken:<token_hash>"` returns token metadata

**Expected Result:** 201 Created, `hms_` token returned, Redis cache populated
**Pass Criteria:** All 3 steps succeed

---

### E2E-007: API Token - Use
**Prerequisites:** `hms_` token from E2E-006

**Steps:**
1. `curl http://localhost:8001/auth/me -H "Authorization: Bearer <hms_token>"`
2. Verify response returns user/service account info

**Expected Result:** 200 OK, identity returned
**Pass Criteria:** Step succeeds

---

### E2E-008: API Token - Revoke
**Prerequisites:** `hms_` token from E2E-006, admin token

**Steps:**
1. `curl -X DELETE http://localhost:8001/admin/api-tokens/<token_id> \
   -H "Authorization: Bearer <admin_token>"`
2. Verify 204 No Content
3. Attempt to use revoked token: `curl http://localhost:8001/auth/me -H "Authorization: Bearer <revoked_token>"`
4. Verify 401 returned

**Expected Result:** 204 on revoke, 401 on subsequent use
**Pass Criteria:** All 4 steps succeed

---

### E2E-009: Quota - Check
**Prerequisites:** User logged in via E2E-001

**Steps:**
1. After login, query quota: `curl http://localhost:8003/quota/me -H "Authorization: Bearer <user_token>"`
2. Verify response shows `limit` and `used` count
3. Verify `used` count starts at 0 for new user

**Expected Result:** 200 OK, quota object with `limit` > 0, `used` = 0
**Pass Criteria:** All 3 steps succeed

---

### E2E-010: Quota - Increment
**Prerequisites:** User token from E2E-009, quota reset to 0

**Steps:**
1. Note current `used` count from E2E-009
2. Make a chat request via router: `curl -X POST http://localhost:8002/router/chat \
   -H "Authorization: Bearer <user_token>" \
   -H "Content-Type: application/json" \
   -d '{"message":"hello","session_id":"test-session-001"}'`
3. Query quota again: `curl http://localhost:8003/quota/me -H "Authorization: Bearer <user_token>"`
4. Verify `used` count incremented by 1

**Expected Result:** `used` count increases by exactly 1
**Pass Criteria:** Increment verified

---

### E2E-011: Quota - Exceeded
**Prerequisites:** Debug endpoint to set quota `used` = `limit` - 1

**Steps:**
1. Reset quota to limit - 1: `curl -X POST http://localhost:8003/quota/debug/reset \
   -H "Authorization: Bearer <admin_token>" \
   -d '{"user_id":"<user_id>","used":<limit_minus_one>}'`
2. Make one more request: `curl -X POST http://localhost:8002/router/chat \
   -H "Authorization: Bearer <user_token>" \
   -H "Content-Type: application/json" \
   -d '{"message":"hello","session_id":"test-session-002"}'`
3. Verify 429 Too Many Requests returned
4. Verify `Retry-After` header present

**Expected Result:** 429 with Retry-After header
**Pass Criteria:** Both steps succeed

---

### E2E-012: Skills - List
**Prerequisites:** None (skills-registry public read)

**Steps:**
1. `curl http://localhost:8004/skills`
2. Verify 200 OK
3. Verify response is a JSON array
4. Verify each skill has `id`, `name`, `version`, `status`

**Expected Result:** 200 OK, array of skill objects
**Pass Criteria:** All 4 steps succeed

---

### E2E-013: Skills - Create
**Prerequisites:** Admin token

**Steps:**
1. `curl -X POST http://localhost:8004/skills \
   -H "Content-Type: application/json" \
   -H "Authorization: Bearer <admin_token>" \
   -d '{"name":"e2e-test-skill","description":"test","version":"1.0.0","config":{"command":"echo test"}}'`
2. Verify 201 Created, skill returned with `id`
3. List skills: `curl http://localhost:8004/skills`
4. Verify new skill appears in list

**Expected Result:** Skill created and retrievable
**Pass Criteria:** All 4 steps succeed

---

### E2E-014: Skills - Update
**Prerequisites:** Skill from E2E-013

**Steps:**
1. `curl -X PUT http://localhost:8004/skills/<skill_id> \
   -H "Content-Type: application/json" \
   -H "Authorization: Bearer <admin_token>" \
   -d '{"description":"updated description","version":"1.0.1"}'`
2. Verify `version` increments (e.g., 1.0.0 → 1.0.1)
3. Verify `updated_at` timestamp changes

**Expected Result:** 200 OK, version incremented
**Pass Criteria:** Both steps succeed

---

### E2E-015: Skills - Archive
**Prerequisites:** Skill from E2E-013

**Steps:**
1. `curl -X DELETE http://localhost:8004/skills/<skill_id> \
   -H "Authorization: Bearer <admin_token>"`
2. Verify 204 No Content
3. List skills: `curl http://localhost:8004/skills`
4. Verify archived skill NOT in public list

**Expected Result:** Skill not in public list (archived)
**Pass Criteria:** All 4 steps succeed

---

### E2E-016: Skills - Hot Reload
**Prerequisites:** At least one active router pod, admin token

**Steps:**
1. Create a test skill: POST to `/skills` (from E2E-013)
2. Update the skill: PUT to `/skills/<id>` with new version
3. Within 5 seconds, verify active router pods receive reload signal (check router logs for `SKILL_RELOAD` event)
4. Send a new chat request to the router and verify the new skill version is used

**Expected Result:** Reload signal received < 5s, new version used in next request
**Pass Criteria:** Hot reload < 5s, correct version used

---

### E2E-017: Router - Route Request
**Prerequisites:** User token from E2E-001, router-service healthy, at least one pod available

**Steps:**
1. `curl -X POST http://localhost:8002/router/chat \
   -H "Authorization: Bearer <user_token>" \
   -H "Content-Type: application/json" \
   -d '{"message":"Hello Hermes","session_id":"test-e2e-017"}'`
2. Verify 200 OK
3. Verify `response` field present in JSON
4. Verify response latency < 10s

**Expected Result:** 200 OK, response returned, latency < 10s
**Pass Criteria:** All 4 steps succeed

---

### E2E-018: Router - Session Lock
**Prerequisites:** Two concurrent request clients (curl processes), session_id shared

**Steps:**
1. Send Request A with `session_id=e2e-018-session`: `curl -X POST http://localhost:8002/router/chat -H "Authorization: Bearer <token>" -d '{"message":"Request A","session_id":"e2e-018-session"}' &`
2. Immediately send Request B with same `session_id`: `curl -X POST http://localhost:8002/router/chat -H "Authorization: Bearer <token>" -d '{"message":"Request B","session_id":"e2e-018-session"}' &`
3. Wait for both responses
4. Verify one request processed immediately, one waited (check timestamps in response metadata)

**Expected Result:** One request processed, one queued and processed after
**Pass Criteria:** Session locking verified, no parallel execution

---

### E2E-019: Router - Pod Pool Exhausted
**Prerequisites:** All agent pods busy (may need to simulate via test config), admin access

**Steps:**
1. Verify pod pool is exhausted (all pods have active sessions)
2. Send new request: `curl -X POST http://localhost:8002/router/chat -H "Authorization: Bearer <token>" -d '{"message":"test","session_id":"test-019"}'`
3. Verify 503 Service Unavailable returned
4. Verify `Retry-After` header present
5. Wait `Retry-After` seconds, resend request
6. Verify 200 OK on retry

**Expected Result:** 503 with Retry-After, then 200 on retry
**Pass Criteria:** All 6 steps succeed

---

### E2E-020: Router - Cold Start
**Prerequisites:** At least one idle hermes-agent pod (no active sessions), ability to measure time

**Steps:**
1. Force-stop all active pods (or use scale-to-zero): `kubectl scale deployment hermes-agent --replicas=0 -n hermes`
2. Wait 30s for pods to terminate
3. Send first request: `time curl -X POST http://localhost:8002/router/chat -H "Authorization: Bearer <token>" -d '{"message":"cold start test","session_id":"test-020"}'`
4. Measure pod startup time from log timestamp to first byte returned

**Expected Result:** Pod started and response returned < 3 seconds
**Pass Criteria:** Cold start latency < 3s

---

### E2E-021: Feishu - Webhook Receive
**Prerequisites:** Feishu bot configured with webhook URL

**Steps:**
1. `curl -X POST http://localhost:8005/feishu/webhook \
   -H "Content-Type: application/json" \
   -d '{"event_type":"message","message":{"text":"test"}}'`
2. Verify 200 OK returned immediately
3. Verify no errors in feishu-bot logs

**Expected Result:** 200 OK, no errors
**Pass Criteria:** All 3 steps succeed

---

### E2E-022: Feishu - Message Reply
**Prerequisites:** Feishu bot token, test user with bot added

**Steps:**
1. Send message via Feishu API to bot: POST to `https://open.feishu.cn/open-apis/bot/v2/hook/<webhook_id>` with test message
2. Verify bot receives event (check feishu-bot logs)
3. Verify bot sends reply to user within 5s

**Expected Result:** Bot receives message, reply sent within 5s
**Pass Criteria:** Both steps succeed

---

### E2E-023: Admin - User List
**Prerequisites:** Admin user logged in to admin-console

**Steps:**
1. Navigate to admin-console at `http://localhost:3000/users`
2. Login as `dev@hermes.local` / `devpassword` if not already logged in
3. Verify paginated user list loads
4. Verify each row shows `email`, `role`, `created_at`
5. Click next page, verify pagination works

**Expected Result:** Paginated user list renders correctly
**Pass Criteria:** All 5 steps succeed

---

### E2E-024: Admin - Quota Config
**Prerequisites:** Admin user, target user ID from E2E-023

**Steps:**
1. Navigate to `http://localhost:3000/users/<user_id>/quota`
2. Change quota limit from default (e.g., 100) to 200
3. Save
4. Verify via API: `curl http://localhost:8003/quota/<user_id> -H "Authorization: Bearer <admin_token>"`
5. Verify `limit` is now 200

**Expected Result:** Quota updated to 200
**Pass Criteria:** All 5 steps succeed

---

### E2E-025: Admin - Audit Logs
**Prerequisites:** Admin user

**Steps:**
1. Navigate to `http://localhost:3000/audit-logs`
2. Login as admin if needed
3. Filter by `event_type=login` and date range = today
4. Verify E2E-001 login event appears
5. Filter by `user_id` = specific user
6. Verify correct events shown

**Expected Result:** Audit logs filterable, events correct
**Pass Criteria:** All 6 steps succeed

---

### E2E-026: LLM - Proxy
**Prerequisites:** Router + LiteLLM + valid LLM API key configured

**Steps:**
1. `curl -X POST http://localhost:8002/router/chat \
   -H "Authorization: Bearer <user_token>" \
   -H "Content-Type: application/json" \
   -d '{"message":"What is 2+2?","session_id":"test-e2e-026"}'`
2. Verify 200 OK
3. Verify response is non-empty
4. Verify request logged in LiteLLM metrics

**Expected Result:** Real LLM response returned via LiteLLM proxy
**Pass Criteria:** All 4 steps succeed

---

### E2E-027: LLM - Model Fallback
**Prerequisites:** LiteLLM configured with primary and fallback model

**Steps:**
1. Configure primary model to return error (via litellm config or mock)
2. Send request: `curl -X POST http://localhost:8002/router/chat -H "Authorization: Bearer <token>" -d '{"message":"test","session_id":"test-027"}'`
3. Verify fallback model used (check LiteLLM logs for `fallback` event)
4. Verify response returned successfully

**Expected Result:** Fallback triggered, response returned
**Pass Criteria:** Both steps succeed

---

### E2E-028: NAS - SQLite WAL
**Prerequisites:** NAS NFS v4 mounted at `/hermes-homes`, hermes-agent pod running

**Steps:**
1. Exec into pod: `kubectl exec -it deploy/hermes-agent -n hermes -- /bin/sh`
2. Write test SQLite WAL: Run a Python script that creates a SQLite DB on `/hermes-homes/<user_id>/test.db` and writes via WAL mode
3. Read back data, verify WAL `-wal` and `-shm` files present
4. Delete DB, verify cleanup

**Expected Result:** WAL operations succeed on NFS v4
**Pass Criteria:** All 4 steps succeed, no file handle errors

---

### E2E-029: NAS - Multi-Pod
**Prerequisites:** Two hermes-agent pods, shared NAS `/hermes-homes`

**Steps:**
1. Pod A writes to shared DB: `sqlite3 /hermes-homes/<user_id>/shared.db "CREATE TABLE t1(id INT); INSERT INTO t1 VALUES(1);"`
2. Simultaneously, Pod B reads: `sqlite3 /hermes-homes/<user_id>/shared.db "SELECT * FROM t1;"`
3. Verify Pod B reads the inserted data (not stale, no corruption)
4. Verify Pod A WAL checkpoint completes without error

**Expected Result:** Concurrent read/write works, no corruption
**Pass Criteria:** All 4 steps succeed

---

### E2E-030: OIDC - User Provisioning
**Prerequisites:** Fresh test OIDC user (not in DB), Keycloak with test user

**Steps:**
1. Ensure test OIDC user does NOT exist in platform DB
2. Complete OIDC login flow (E2E-002) with test user
3. Query users: `curl http://localhost:8001/admin/users -H "Authorization: Bearer <admin_token>"`
4. Verify new user created with correct `email`, `sub` claim from OIDC

**Expected Result:** New user provisioned on first OIDC login
**Pass Criteria:** All 4 steps succeed

---

## 4. Blockers & Acceptance Criteria

### 4.1 MVP Phase 1 Acceptance Criteria (from Delivery Plan)

| Criteria | Target | Measurement |
|----------|--------|-------------|
| 50 真实用户可登录 | All 50 users can authenticate successfully | Login success rate > 99% over 24h |
| 飞书Bot可用 | Bot responds to messages within 5s | 100% of test messages replied |
| 会话隔离验证 | Sessions isolated per user, no cross-talk | E2E-018 passes 100% |

### 4.2 Quantitative SLAs

| Metric | Target | Measurement Method |
|--------|--------|--------------------|
| Login success rate | > 99% | Auth-service logs / 24h window |
| P99 chat request latency | < 2s | Router-service metrics |
| Quota enforcement accuracy | 100% | E2E-011 automated test |
| Skills hot reload time | < 5s | E2E-016 measured timestamp |
| NAS WAL reliability | 0 corruption events | E2E-028, E2E-029 automated |

### 4.3 Blocker Definition

Any of the following blocks Phase 1 MVP launch:
- E2E-001 (Mock Login) fails
- E2E-002 (OIDC Login) fails
- E2E-009 (Quota Check) fails
- E2E-011 (Quota Exceeded) fails
- E2E-017 (Router Route) fails
- E2E-021 (Feishu Webhook) fails
- E2E-026 (LLM Proxy) fails
- E2E-028 (NAS WAL) fails
- E2E-030 (OIDC Provisioning) fails

---

## 5. Bug Severity Definitions

| Severity | Definition | Example | Impact |
|----------|------------|---------|--------|
| **Critical** | System down, data loss, or security breach | OIDC token validation bypass, user data corruption | Launch blocker |
| **High** | Major feature broken, workaround difficult | Quota not enforced, session isolation broken | Launch blocker |
| **Medium** | Feature partially works, workaround exists | Skills page slow (>5s load), pagination broken | Fix before GA |
| **Low** | Cosmetic, minor UX issue | Typo in error message, button misalignment | Fix in sprint |

---

## 6. Test Environment Setup

### 6.1 Local Docker Compose Setup

```bash
# Navigate to deploy directory
cd /Users/ailabuser1/Desktop/gitcode/hermes-agent/deploy/docker-compose

# Start all services
docker compose up -d

# Wait for all services to be healthy
sleep 30

# Verify all services are running
docker compose ps

# Expected output: all services show "healthy" or "running"

# Verify individual service health
curl http://localhost:8001/health   # auth-service
curl http://localhost:8002/health   # router-service
curl http://localhost:8003/health   # quota-service
curl http://localhost:8004/health   # skills-registry
curl http://localhost:8005/health   # feishu-bot
curl http://localhost:4000/health   # litellm (if health endpoint exposed)
```

### 6.2 Staging K8s Setup

```bash
# Apply base configuration
kubectl apply -k /Users/ailabuser1/Desktop/gitcode/hermes-agent/k8s/overlays/staging

# Wait for all deployments
kubectl rollout status deployment/auth-service -n hermes-staging
kubectl rollout status deployment/router-service -n hermes-staging
kubectl rollout status deployment/quota-service -n hermes-staging
kubectl rollout status deployment/skills-registry -n hermes-staging
kubectl rollout status deployment/feishu-bot -n hermes-staging
kubectl rollout status deployment/admin-console -n hermes-staging

# Verify all pods running
kubectl get pods -n hermes-staging

# Port-forward for local testing
kubectl port-forward svc/auth-service 8001:8001 -n hermes-staging &
kubectl port-forward svc/router-service 8002:8002 -n hermes-staging &
```

### 6.3 Test Data Setup

```bash
# Create test users via auth-service admin API
# dev@hermes.local - admin (pre-seeded in init script)
# test@hermes.local - regular user (create via admin API)

# Test admin credentials
ADMIN_EMAIL="dev@hermes.local"
ADMIN_PASSWORD="devpassword"

# Get admin token
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" | \
  jq -r '.access_token')

# Create test user
curl -X POST http://localhost:8001/admin/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"email":"test@hermes.local","password":"testpassword","role":"user"}'

# Reset quota for test user (via debug endpoint)
curl -X POST http://localhost:8003/quota/debug/reset \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"user_id":"<test_user_id>","used":0}'
```

---

## 7. Test Data Requirements

### 7.1 Test Users

| Email | Password | Role | Purpose |
|-------|----------|------|---------|
| dev@hermes.local | devpassword | admin | Primary admin testing |
| test@hermes.local | testpassword | user | Regular user testing |

### 7.2 Test Skills

| Skill ID | Name | Purpose |
|----------|------|---------|
| skill-mock-1 | Mock Skill 1 | Skills list/CRUD tests |
| skill-mock-2 | Mock Skill 2 | Hot reload tests |

### 7.3 Test Sessions

| Session ID | Purpose |
|------------|---------|
| test-e2e-017 | Router request routing |
| test-e2e-018 | Session lock testing |
| test-e2e-026 | LLM proxy testing |

---

## 8. Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| QA Engineer | _________________ | __________ | _________________ |
| Tech Lead | _________________ | __________ | _________________ |
| Product Owner | _________________ | __________ | _________________ |

---

## Appendix A: Service Endpoint Reference

| Service | Base URL (Local) | Key Endpoints |
|---------|------------------|---------------|
| auth-service | http://localhost:8001 | `/auth/login`, `/auth/me`, `/auth/token/refresh`, `/admin/users`, `/admin/api-tokens`, `/admin/audit-logs` |
| router-service | http://localhost:8002 | `/router/chat`, `/router/health` |
| quota-service | http://localhost:8003 | `/quota/me`, `/quota/<user_id>`, `/quota/debug/reset` |
| skills-registry | http://localhost:8004 | `/skills`, `/skills/<id>`, `PUT /skills/<id>`, `DELETE /skills/<id>` |
| feishu-bot | http://localhost:8005 | `/feishu/webhook` |
| admin-console | http://localhost:3000 | `/users`, `/users/<id>/quota`, `/audit-logs` |
| LiteLLM | http://localhost:4000 | `/v1/chat/completions` |

## Appendix B: Automated Test Script Template

```bash
#!/bin/bash
# e2e-smoke.sh — Run P0 tests against local Docker Compose

set -e

BASE_URL="${BASE_URL:-http://localhost}"
ADMIN_EMAIL="${ADMIN_EMAIL:-dev@hermes.local}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-devpassword}"

pass=0; fail=0

run_test() {
  local name="$1"; shift
  echo -n "[TEST] $name ... "
  if "$@"; then
    echo "PASS"; ((pass++))
  else
    echo "FAIL"; ((fail++))
  fi
}

# E2E-001: Mock Login
run_test "E2E-001 Auth Mock Login" bash -c '
  RESPONSE=$(curl -s -X POST "$BASE_URL:8001/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}")"
  echo "$RESPONSE" | jq -e ".access_token" > /dev/null
'

# E2E-009: Quota Check
run_test "E2E-009 Quota Check" bash -c '
  curl -s "$BASE_URL:8003/quota/me" -H "Authorization: Bearer $TOKEN" | \
    jq -e ".limit > 0" > /dev/null
'

# E2E-012: Skills List
run_test "E2E-012 Skills List" bash -c '
  curl -s "$BASE_URL:8004/skills" | jq -e "type == \"array\"" > /dev/null
'

echo ""
echo "Results: $pass passed, $fail failed"
exit $fail
```
