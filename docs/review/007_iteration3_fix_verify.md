# Iteration 3: Fix Verification + Edge Case Testing

**Date**: 2026-05-27
**Scope**: Fix 3 access control bugs, verify fixes, edge case testing

---

## Fixes Applied & Verified

### Fix 1: `/runs/{id}/rerun` — Ownership check ✅
**Before**: Any user could rerun any other user's run
**After**:
```
Bob → rerun alice's run: 403 ✅
Default → rerun alice's run: 403 ✅
Admin → rerun alice's run: 200 ✅
Alice → rerun own run: 200 ✅
```

### Fix 2: `/workflows/{id}/cancel` — Ownership check ✅
**Before**: Any user could cancel any running workflow
**After**:
```
Bob → cancel alice's workflow: 403 ✅
Default → cancel alice's workflow: 403 ✅
Alice → cancel own workflow: 200 ✅
```

### Fix 3: `/runs/{id}/resume` — Ownership check ✅
**Before**: Any user could resume any paused workflow
**After**:
```
Bob → resume alice's workflow: 403 ✅
Default → resume alice's run: 403 ✅
Alice → resume own workflow: 200 ✅
```

---

## Edge Case Test Results

### ✅ Delete Cascade
- Bob → delete alice's run: **403** (correct)
- Alice → delete own run: **200** (correct)
- Alice's run count decreased from 5 to 4 (correct)
- Double delete: **404** on second attempt (correct)

### ✅ Anonymous/No-auth User
- No auth → resolves to "default" user (by design)
- Sees default user's 20 runs (correct)

### ✅ Invalid User ID
- `X-User-Id: nonexistent_user` → resolves to "default" (fallback)
- Sees default user's 20 runs (fallback behavior)

### ✅ Empty User ID
- `X-User-Id: ""` → resolves to "default" (fallback)
- Frontend localStorage with empty string falls back correctly

### ⚠️ Private Workflow Access (Edge Case 7)
- Bob can START a workflow using alice's private workflow name
- **But**: Bob can't see alice's private workflow in the definitions list
- **And**: The workflow dir resolves to non-existent path, so agent MDs won't load
- **Impact**: Low — Bob would need to know the exact workflow name AND provide agents inline
- **Recommendation**: Consider validating that the workflow dir exists before starting

### ✅ Chart Render (No Auth)
- `POST /charts` returns 200 without auth (by design)
- Charts are tied to running workflows, not users

### ✅ Workflow Status Endpoint
- `GET /workflows/{id}` only works for in-memory (running) workflows
- Completed runs use `GET /runs/{id}` which has auth checks
- No auth check on `/workflows/{id}` but it only exposes workflow status, not data

---

## Code Changes

**File**: `server/routes.py`

1. **rerun** (line ~1343-1354): Added ownership check before rerun
2. **cancel** (line ~1177-1185): Added ownership check using repository data
3. **resume** (line ~1272-1283): Added ownership check using repository data, removed duplicate data/user fetches

All three use consistent pattern:
```python
user = get_current_user(request)
user_mgr = get_user_manager()
is_admin = user_mgr.is_admin(user)
if not is_admin and data.get("user_id", "default") != user.user_id:
    raise HTTPException(status_code=403, detail="Not your run")
```

---

## Updated Issue List

### Fixed in Iteration 3
- ~~🔴 `/runs/{id}/rerun` 无所有权检查~~ → ✅ Fixed & Verified
- ~~🔴 `/runs/{id}/resume` 无所有权检查~~ → ✅ Fixed & Verified
- ~~🔴 `/workflows/{id}/cancel` 无所有权检查~~ → ✅ Fixed & Verified

### Remaining Issues
4. ⚠️ Conversation 持久化缺口: 87% runs have no conversation
5. ⚠️ Benchmark 无用户隔离
6. ⚠️ UserManager 无热更新
7. ℹ️ Private workflow name can be used by other users (low impact)

---

**Test completed**: 2026-05-27
