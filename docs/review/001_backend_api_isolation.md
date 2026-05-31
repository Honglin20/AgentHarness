# Backend API User Isolation Test
**Date**: 2026-05-26T16:57:18Z
**Note**: Users recreated via admin API before test

## 1. User Resolution (/me)

- default → `{"user_id":"default","name":"Default User","role":"developer"}`
- alice → `{"user_id":"alice","name":"Alice","role":"developer"}`
- bob → `{"user_id":"bob","name":"Bob","role":"developer"}`
- admin → `{"user_id":"admin","name":"Admin","role":"admin"}`
- API key key_alice → `{"user_id":"default","name":"Default User","role":"developer"}`

## 2. Run Listing Isolation

| User | Runs | Expected |
|------|------|----------|
| default | 19 | own runs |
| alice | 0 | 0 (new user) |
| bob | 0 | 0 (new user) |
| admin | 22 | all runs |

### Cross-user overlap check
- Default IDs: ['8422c8df-11c9-4380-94be-b24eadcef750', '2b4354e8-df12-47a5-873e-24540b86c417', '59ec6302-fc6a-40a3-9388-7478960b28a7', 'e8fda71f-b8e3-45eb-be5d-5af49f325e0f', '0f37d9b9-7a92-494b-acce-ac80cc398b82',
- Alice IDs: []
- Bob IDs: []
- PASS: Alice sees no default runs

## 3. Run Detail Access Control

Test run_id: `8422c8df-11c9-4380-94be-b24eadcef750`

- Default → own run: `200` (expected: 200) ✅
- Alice → default's run: `403` (expected: 403) ✅
- Bob → default's run: `403` (expected: 403) ✅
- Admin → default's run: `200` (expected: 200) ✅

## 4. Conversation Update Access Control

- Alice updates default's conversation: `403` (expected: 403) ✅
- Default updates own conversation: `200` (expected: 200) ✅

## 5. Charts Update Access Control

- Alice updates default's charts: `403` (expected: 403) ✅

## 6. Run Delete Access Control

- Alice deletes default's run: `403` (expected: 403) ✅

## 7. Workflow Definitions Isolation

- default: 15 workflows → `['ask_human_demo', 'chart_demo', 'code_review', 'coder_review_loop', 'conditional_route', 'deep_analysis', 'demo_pipeline', 'eval_code_quality', 'eval_demo', 'full_extensions', 'loop_retry', 'parallel`
- alice: 14 workflows → `['ask_human_demo', 'chart_demo', 'code_review', 'coder_review_loop', 'conditional_route', 'deep_analysis', 'demo_pipeline', 'eval_code_quality', 'eval_demo', 'full_extensions', 'loop_retry', 'parallel`
- admin: 12 workflows → `['ask_human_demo', 'chart_demo', 'code_review', 'coder_review_loop', 'conditional_route', 'deep_analysis', 'demo_pipeline', 'eval_code_quality', 'eval_demo', 'full_extensions', 'loop_retry', 'parallel`

## 8. Benchmark Endpoints

- Total benchmarks: 2
- 'code-review-v1' results: 12

---

## Summary

### PASS (7/7)
- ✅ User resolution via X-User-Id header
- ✅ Run listing isolation (alice=0, bob=0, default=19, admin=22)
- ✅ Run detail access control (403 for non-owners)
- ✅ Conversation update access control (403 for non-owners)
- ✅ Charts update access control (403 for non-owners)
- ✅ Run delete access control (403 for non-owners)
- ✅ Workflow definitions isolation (shared/private/legacy correctly scoped)

### Issues Found
1. **⚠️ Stale UserManager**: Users added to users.json manually are NOT picked up by running server. No auto-reload mechanism. Must recreate via `POST /api/users` or restart server.
2. **⚠️ Duplicate workflow names**: Default user sees `code_review`, `conditional_route`, `eval_code_quality` as both shared and legacy. Frontend needs dedup by name.
3. **⚠️ API key `key_alice` resolves to default**: Old API keys from manually edited users.json are orphaned after server-side user recreation.

### Architecture Note
- Shared workflows: 12 (visible to all users)
- Legacy workflows: 3 (visible only to default/null user)
- Alice private: 2 (`my_private_workflow`, `summary`)
- Admin sees only shared (12) — correct, no private workflows for admin

---
**Test completed**: 2026-05-26T16:57:19Z
