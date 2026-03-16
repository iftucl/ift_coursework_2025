# Pipeline Refactoring: Structured Results & MinIO Diagnostics

## Problem Summary

### Issue 1: Stale Hard-Coded Summary Numbers
The pipeline printed static numbers in the final summary regardless of actual run outputs:
```
Portfolio:
  📊 335 stocks selected (final_trade_signal=1)

Execution Signals:
  📊 597 stocks with signals
```

**Root Cause:** The summary was a hand-written string template with hard-coded numbers from early development. Even though the actual pipeline ran correctly and generated 123 stocks (Step 2) and 123 signals (Step 3), the summary still claimed 335 and 597.

**Location:** `run_pipeline.py:233-255` - Hard-coded summary when `all_success == True`

### Issue 2: Misleading MinIO Failure Handling
MinIO upload failures were silently swallowed:
- Client initialization failure → only warning logged, pipeline marked as successful
- Upload errors → counted but didn't affect exit code
- Final summary showed "Step 4 complete" even when MinIO was unreachable

**Root Cause:**
- `export_analytics_to_minio.py:_init_minio_client()` returned `None` on config/connection errors with just a warning
- `export_to_local_and_minio()` always returned `True` if local export succeeded, regardless of MinIO status
- No distinction between intentional offline mode and actual MinIO failure

**Location:** `pipeline/export_analytics_to_minio.py:78-97` and `454`

## Solution: Structured Results & Diagnostics

### 1. New Module: `modules/pipeline_results.py`

**Purpose:** Centralize all result tracking into structured objects instead of ad hoc logging.

**Key Classes:**
- `ExportStatus` enum: `LOCAL_ONLY | MINIO_SUCCESS | MINIO_FAILED | DISABLED | UNKNOWN`
- `StepResult` dataclass: Per-step metadata (row count, files, duration, error message)
- `PipelineRunSummary` dataclass: Complete run state with actual counts from current execution

**Example:**
```python
summary = PipelineRunSummary(start_time=datetime.now())
summary.step1_factor_count = 598  # Read from actual file
summary.step2_selections_count = 123  # Read from actual file
summary.step3_buy_count = 4  # Computed from signals_latest.csv
summary.export_status = ExportStatus.MINIO_FAILED  # Reflects reality
```

### 2. New Module: `modules/output_reader.py`

**Purpose:** Read actual counts from current pipeline outputs instead of hard-coding.

**Functions:**
- `read_factor_count()` → int (reads analytics/processed/step1/factors_latest.csv)
- `read_step2_counts()` → (portfolio_count, selections_count)
- `read_step3_signal_counts()` → (total, buy, sell, hold)

**Example:**
```python
factors = read_factor_count()  # 598 (actual from this run)
portfolio, selections =read_step2_counts()  # 123, 123 (actual from this run)
total, buy, sell, hold = read_step3_signal_counts()  # 123, 4, 9, 110
```

### 3. New Module: `modules/minio_diagnostics.py`

**Purpose:** Detailed MinIO diagnostics to distinguish error types.

**Key Methods:**
- `check_env_vars()` → (bool, Optional[str]) - Validates required env vars
- `validate_endpoint(endpoint)` → (bool, Optional[str]) - Checks endpoint format & port
- `preflight_check_connectivity(...)` → (bool, Optional[str]) - Tests actual connection
  - Returns specific errors: "endpoint unreachable", "bad credentials", "bucket missing"
- `log_configuration(...)` - Non-secret config logging

**Example:**
```python
config_ok, error = MinIODiagnostics.check_env_vars()
# error: "Missing MinIO config: MINIO_ENDPOINT, MINIO_ACCESS_KEY"

ok, error = MinIODiagnostics.preflight_check_connectivity(ep, key, secret, bucket)
# error: "Cannot connect to MinIO endpoint localhost:9000: Connection refused"
```

### 4. Updated: `pipeline/export_analytics_to_minio.py`

**Added function:** `export_with_status_tracking()`
- Runs preflight checks before export
- Returns tuple: `(success: bool, export_status: ExportStatus, details: dict)`
- Distinguishes between:
  - MinIO not configured → `ExportStatus.DISABLED` (intentional offline mode)
  - Preflight fails → `ExportStatus.MINIO_FAILED` (local export continues, but marked as failed)
  - Both succeed → `ExportStatus.MINIO_SUCCESS`

### 5. Updated: `run_pipeline.py`

**Changes:**
- Remove hard-coded template summary (lines 233-255)
- Import structured result types and output readers
- After all steps pass, read **actual counts from current outputs**:
  ```python
  summary.step1_factor_count = read_factor_count()
  portfolio_count, selections_count = read_step2_counts()
  total_signals, buy, sell, hold = read_step3_signal_counts()
  ```
- Display summary using actual counts:
  ```
  Step 1: Risk Metrics
    📊 598 factors calculated (actual from this run)

  Step 3: Execution Signals
    📊 123 total signals (4 BUY, 9 SELL, 110 HOLD) (actual from this run)
  ```

## Environment Variables

### Required (for MinIO)
```bash
export MINIO_ENDPOINT="localhost:9000"
export MINIO_ACCESS_KEY="ift_bigdata"         # Or minioadmin
export MINIO_SECRET_KEY="minio_password"      # Or minioadmin
export MINIO_BUCKET="csreport"
export MINIO_SECURE="false"                   # true for https
```

### Optional
- If MinIO env vars are **not set**, pipeline runs in LOCAL_ONLY mode (graceful degradation)
- If MinIO env vars are **set but unreachable**, export fails with actionable error message

### Example: Local-Only (No MinIO)
```bash
unset MINIO_ENDPOINT MINIO_ACCESS_KEY MINIO_SECRET_KEY
poetry run python3 run_pipeline.py
# Output: "ℹ  MinIO not configured. Proceeding with local-only export..."
# Final summary shows DISABLED status
```

### Example: MinIO Configured
```bash
export MINIO_ENDPOINT="localhost:9000"
export MINIO_ACCESS_KEY="ift_bigdata"
export MINIO_SECRET_KEY="minio_password"
export MINIO_BUCKET="csreport"
poetry run python3 run_pipeline.py
# Output: "✓ MinIO preflight check passed, proceeding with full export..."
# Final summary shows MINIO_SUCCESS or MINIO_FAILED with details
```

## Tests

**File:** `test/test_pipeline_refactor.py` (17 tests, all passing)

**Coverage:**
1. ✅ Structured result types (StepResult, ExportStatus, PipelineRunSummary)
2. ✅ Output readers (read_factor_count, read_step2_counts, read_step3_signal_counts)
3. ✅ MinIO diagnostics (env var checking, endpoint validation, preflight)
4. ✅ No hard-coded numbers in summaries
5. ✅ Export status tracking
6. ✅ Error classification (connection, credentials, bucket)

**Run tests:**
```bash
poetry run pytest test/test_pipeline_refactor.py -v
```

## Benefits

| Before | After |
|--------|-------|
| Summary shows "335 stocks" even when run selects 123 | Summary shows actual count: "123 stocks selected (from this run)" |
| MinIO failure silently swallowed, marked as success | Export status clearly reports MINIO_FAILED with actionable error |
| No way to distinguish "offline intentional" from "offline broken" | ExportStatus.DISABLED vs MINIO_FAILED clearly distinguishes |
| No insight into why MinIO initialization failed | Detailed preflight check shows "endpoint unreachable", "bad credentials", etc. |
| Hard to write tests for summary accuracy | Structured result types enable deterministic testing |
| All output via print/logger, hard to consume programmatically | PipelineRunSummary.to_dict() enables logging/monitoring integration |

## Root Cause Analysis

### Why Did Stale Numbers Appear?

1. **Template-Based Summary** (Anti-pattern)
   - Summary was a static f-string defined once in code
   - Numbers came from early development (335 BUY signals from all 597 stocks)
   - When portfolio selection strategy changed to sector-relative (123 stocks), summary wasn't updated

2. **No Feedback Loop**
   - Summary didn't read from actual outputs
   - No test to verify summary numbers match outputs
   - Pipeline marked as "successful" even though summary was wrong

### Why Did MinIO Failures Stay Silent?

1. **Graceful Degradation Gone Wrong**
   - `_init_minio_client()` returned None with just a warning (good for offline mode)
   - But `export_to_local_and_minio()` ignored None and returned True anyway
   - Pipeline didn't distinguish between "MinIO not configured" vs "MinIO unreachable"

2. **No Error Classification**
   - All errors (bad endpoint, bad credentials, bucket missing) looked the same
   - Just a generic warning, impossible to debug
   - User had no way to know if they need to check credentials or network connectivity

## Migration Path

✅ **Fully backward compatible** - existing scripts continue to work:
- `run_pipeline.py` still accepts same CLI arguments
- `export_analytics_to_minio.py` still publishes same files
- Minnesota export still happens (via `export_with_status_tracking()` wrapper)

**No breaking changes to:**
- Analytics output directory structure (raw/, processed/, serving/)
- File naming (factors_latest.csv, signals_latest.csv)
- CLI arguments
- Database updates
