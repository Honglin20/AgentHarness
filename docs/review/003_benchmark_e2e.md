# Benchmark E2E Review

**Date**: 2026-05-27
**Scope**: Benchmark run flow, result isolation, comparison, history

---

## Test Results

### 1. Benchmark API Endpoints

| Endpoint | Status | Notes |
|----------|--------|-------|
| GET /benchmarks | ✅ 200 | Lists all benchmarks (2 found) |
| GET /benchmarks/{name} | ✅ 200 | Returns benchmark definition |
| GET /benchmarks/{name}/results | ✅ 200 | Lists all results (12 found) |
| GET /benchmarks/{name}/results/{id} | ✅ 200 | Returns specific result |

### 2. Benchmark User Isolation

| Check | Result | Impact |
|-------|--------|--------|
| Benchmark visibility | ⚠️ **All users see all benchmarks** | By design? Benchmarks are shared resources |
| Result visibility | ⚠️ **All users see all results** | No user_id filtering |
| Result user_id | ⚠️ **NOT SET in result records** | Benchmark result JSON has no user_id field |
| Run ownership | ⚠️ **No auth check on results** | Any user can access any benchmark result |

**Root Cause**: `BenchmarkStore` has no user_id awareness:
- `save_result()` doesn't store user_id
- `list_results()` doesn't filter by user
- API endpoints don't pass user context to benchmark operations

**However**: Individual workflow runs created by benchmarks DO have user_id:
- `_create_and_start_workflow()` receives `user_id` from `run_benchmark()`
- Run detail access (`GET /runs/{id}`) properly checks ownership
- Conversation/charts access properly checks ownership

### 3. Benchmark Run Flow

```
POST /benchmarks/{name}/run
  → get_current_user() → user_id
  → _create_and_start_workflow(user_id=user_id)  ✅ user_id propagated
  → store.save_result()                           ⚠️ user_id NOT stored in result
  → return BenchmarkRunSummary
```

### 4. Benchmark Result Enrichment

`_enrich_benchmark_result()` (routes.py:1074-1141):
- Updates task status from live workflow data
- Extracts scores from judge outputs
- Extracts duration from trace
- Computes avg_score
- Persists enriched data back to disk
- ✅ Works correctly for updating status/scores

### 5. Benchmark Comparison (Frontend)

`BenchmarkCompare.tsx`:
- ✅ Fetches results via `fetchWithAuth` (authenticated)
- ✅ Sorts by created_at (newest first)
- ✅ Auto-selects 2 most recent runs for comparison
- ✅ Supports run toggle for custom selection
- ✅ Generates grouped bar charts for multi-run comparison
- ✅ Shows scores table with per-task breakdown
- ✅ History tab shows score trend over time
- ✅ Polls every 10s while benchmark is running
- ✅ Auto-refreshes on batch completion
- ⚠️ No user filtering — shows ALL results from ALL users

### 6. Result Enrichment with Live Data

```python
# _enrich_benchmark_result checks repo for live data
for tr in task_results:
    data = repo.get(wid)      # Gets live workflow data
    tr["status"] = data["status"]
    # Extracts score, duration from workflow result
```

- ✅ Status updated from live data
- ✅ Scores extracted from _judge_ outputs
- ✅ Duration extracted from trace
- ✅ Enriched data persisted to disk

---

## Issues Found

### Critical
None — benchmarks work correctly for their current design.

### Isolation Gap (by design?)
1. **⚠️ Benchmarks are global resources** — no user ownership or filtering
   - All users see all benchmarks and results
   - Results don't store user_id
   - No access control on benchmark endpoints
   - This may be intentional — benchmarks as shared team resources

### Minor
2. **⚠️ Run results in benchmark have `status=running` but are persisted**
   - 10 out of 12 results show `status=running` but exist on disk
   - This means `_enrich_benchmark_result` hasn't updated them (workflows completed but enrichment didn't run)
   - Likely because server restarted — enrichment only runs when results are listed and workflows are in-memory

3. **ℹ️ Duplicate `formatOutputAsMd` function**
   - Duplicated in `useWorkflowEvents.ts` and `eventRouter.ts`
   - Should be shared utility

---

## Recommendation

If benchmark isolation is needed:
1. Add `user_id` to `save_result()` in BenchmarkStore
2. Add `user_id` filtering to `list_results()`
3. Pass user context through benchmark API endpoints
4. Add ownership checks to benchmark result access

If benchmarks are meant to be shared (current behavior):
1. Document that benchmarks are shared resources
2. Consider adding user attribution (who ran it) without access restriction

---

**Test completed**: 2026-05-27
