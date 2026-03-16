# Step 4 Status Semantics Fix

## Problem Summary

Despite previous refactoring, Step 4 was still incorrectly reporting "PASS" when MinIO failed. For example:
- MinIO client fails with `InvalidAccessKeyId`
- Logs correctly show "MinIO not available (local publishing only)"
- BUT final summary still shows "✓ Step 4 complete: 638 files published (local + MinIO)" with status "PASS"

**Root Cause:**
- `run_command()` returned only a bool (success/failure) without capturing Step 4's actual export_status
- Pipeline couldn't distinguish between MinIO SUCCESS vs MINIO_FAILED vs DISABLED
- The text "local + MinIO" appeared regardless of MinIO's actual state
- No support for MINIO_REQUIRED environment variable

## Solution: Structured Status Communication

### 1. Modified `run_command()` Function
**Changed:** Return type from `bool` → `tuple(bool, dict)`
- Now returns `(success, extra_data)`
- Step 4 returns `extra_data` containing JSON-parsed export status from subprocess
- Other steps return empty dict

```python
def run_command(script_name: str, description: str) -> tuple:
    # ... existing code ...
    result = subprocess.run([poetry_exe, 'run', 'python3', script_name],
                           capture_output=True, text=True)

    # For Step 4, parse __EXPORT_STATUS_JSON__ from stdout
    if 'export_analytics_to_minio' in script_name:
        for line in result.stdout.split('\n'):
            if '__EXPORT_STATUS_JSON__:' in line:
                json_str = line.split('__EXPORT_STATUS_JSON__:')[1]
                extra_data = json.loads(json_str)  # Captures export_status

    return True/False, extra_data
```

### 2. Updated `export_analytics_to_minio.py`

**Added:** New `export_with_status_tracking()` function
- Performs MinIO diagnostics before export
- Returns `(success, export_status, details)` tuple
- Distinguishes 4 export modes:
  - `MINIO_SUCCESS`: Both local and MinIO uploads succeeded
  - `MINIO_FAILED`: Local succeeded, MinIO failed (with error details)
  - `LOCAL_ONLY`: Local succeeded, MinIO not configured but files ready
  - `DISABLED`: MinIO explicitly disabled (intentional offline mode)

**Updated:** `__main__` section
- Calls `export_with_status_tracking()` instead of `export_to_local_and_minio()`
- Outputs JSON status marker for run_pipeline.py to parse:
  ```python
  status_output = {
      'success': success,
      'export_status': export_status.value,  # 'minio_success', 'minio_failed', etc.
      'minio_configured': details['minio_configured'],
      'minio_endpoint': details['minio_endpoint'],
      'minio_bucket': details['minio_bucket'],
      'minio_connection_error': details['minio_connection_error'],
  }
  print(f"__EXPORT_STATUS_JSON__:{json.dumps(status_output)}")
  ```

### 3. Updated `run_pipeline.py` Main Loop

**Fixed:** Tuple unpacking and status tracking
```python
for i, (script, description) in enumerate(pipeline_steps, 1):
    success, extra_data = run_command(script, description)  # Now unpacks tuple
    results.append((description, success, extra_data))

    # Track Step 4's export_status
    if i == 4 and 'export_status' in extra_data:
        step4_export_status = extra_data['export_status']

    # Steps 1-3: critical (halt on failure)
    # Step 4: optional unless MINIO_REQUIRED=true
    if not success and i < 4:
        break
    elif not success and i == 4:
        minio_required = os.getenv("MINIO_REQUIRED", "false").lower() == "true"
        if minio_required:
            logger.error("❌ MINIO_REQUIRED=true, but MinIO export failed.")
            break
```

### 4. Proper Status Display

**Step Summary Lines:**
- Shows different status for Step 4 based on export_status:
  - `✅ PASS` → MinIO succeeded
  - `⚠️  PARTIAL` → MinIO failed or local-only
  - `⚠️  SKIPPED` → MinIO disabled
  - `❌ FAIL` → Export failed entirely

**Final Summary Message:**
- Shows explicit export status:
  ```
  Step 4: All files published (local + MinIO)           ← Only if MINIO_SUCCESS
  ⚠️  Step 4: Local succeeded, MinIO failed (error)    ← If MINIO_FAILED
  ✓ Step 4: Local export succeeded (MinIO disabled)    ← If DISABLED
  ```
- "local + MinIO" text **never** appears unless MinIO actually succeeded
- Includes error details when MinIO fails

## Environment Variables

### MINIO_REQUIRED (NEW)
- **Default:** `false` (optional)
- **When true:** Pipeline fails if MinIO export fails
- **When false:** Pipeline succeeds if Steps 1-3 succeed (Step 4 optional)

Examples:
```bash
# MinIO optional (default) - local-only export is acceptable
poetry run python3 run_pipeline.py
# Output: "⚠️  PARTIAL - Step 4" if MinIO fails, but exit code 0

# MinIO required - fail if MinIO unavailable
export MINIO_REQUIRED=true
poetry run python3 run_pipeline.py
# Output: "❌ FAIL - Step 4" and exit code 1 if MinIO fails
```

### Existing MinIO Variables
```bash
export MINIO_ENDPOINT="localhost:9000"
export MINIO_ACCESS_KEY="ift_bigdata"
export MINIO_SECRET_KEY="minio_password"
export MINIO_BUCKET="csreport"
export MINIO_SECURE="false"  # or "true" for HTTPS
```

## Examples: Different Scenarios

### Scenario 1: MinIO Success
```
MinIO configured ✓
Preflight check ✓
Upload to MinIO ✓

Summary:
  ✅ PASS - Step 4
  ✓ Step 4: All files published (local + MinIO)
Exit code: 0
```

### Scenario 2: MinIO Fails (MINIO_REQUIRED=false)
```
MinIO configured ✓
Preflight check ✗ (Cannot connect to endpoint)
Fallback to local-only ✓

Summary:
  ⚠️  PARTIAL - Step 4
  ⚠️  Step 4: Local succeeded, MinIO failed (Cannot connect to MinIO endpoint localhost:9999)
Exit code: 0 (trading can proceed with local signals)
```

### Scenario 3: MinIO Not Configured
```
MinIO not configured
Local export ✓

Summary:
  ⚠️  SKIPPED - Step 4
  ✓ Step 4: Local export succeeded (MinIO not configured)
Exit code: 0
```

### Scenario 4: MinIO Required But Fails
```
MINIO_REQUIRED=true
MinIO configured ✓
Preflight check ✗
Halt pipeline ✗

Summary:
  ❌ FAIL - Step 4
  ❌ MINIO_REQUIRED=true, but MinIO export failed
Exit code: 1
```

## Changes Made

### Files Modified
1. **pipeline/export_analytics_to_minio.py**
   - Added `export_with_status_tracking()` function (lines 472-538)
   - Fixed `__main__` section to output JSON status
   - Now properly distinguishes export modes (MINIO_SUCCESS, MINIO_FAILED, LOCAL_ONLY, DISABLED)

2. **run_pipeline.py**
   - Added `import os` (line 45)
   - Modified `run_command()` to return tuple (lines 65-141)
   - Updated main loop to unpack tuples and track Step 4 status (lines 243-262)
   - Rewrote summary section with proper status semantics (lines 265-387)
   - Implemented MINIO_REQUIRED logic (lines 258-262, 272)

3. **test/test_pipeline_refactor.py**
   - Added `TestStep4StatusSemantics` class with 8 new tests
   - Tests verify: status values, enum correctness, MINIO_REQUIRED parsing, JSON format

### Key Features
✅ **Proper Status Semantics:**
- Step 4 shows ✅ PASS only if MinIO succeeded
- Shows ⚠️  PARTIAL or ⚠️  SKIPPED for non-critical MinIO failures
- Shows ❌ FAIL only for actual critical failures

✅ **Never Mislead User:**
- "local + MinIO" text only appears when MinIO actually succeeded
- Error details shown when MinIO fails
- Clear distinction between configured+failed vs. not-configured

✅ **MINIO_REQUIRED Support:**
- Optional by default (Step 4 doesn't block pipeline)
- Fail-fast when MINIO_REQUIRED=true and MinIO unavailable
- Graceful degradation when MINIO_REQUIRED=false (default)

✅ **Backward Compatible:**
- All pipeline step changes optional/non-breaking
- Existing CLI arguments still work
- Export files unchanged

## Testing

All 25 tests pass, including:
- Structured result types (4 tests)
- Output readers (3 tests)
- MinIO diagnostics (6 tests)
- No hard-coded numbers (2 tests)
- Export status tracking (2 tests)
- **Step 4 status semantics (8 NEW tests)** ✅

```bash
poetry run pytest test/test_pipeline_refactor.py -v
# OR
poetry run pytest test/test_pipeline_refactor.py::TestStep4StatusSemantics -v
```

## Verification

**Dry-run:**
```bash
poetry run python3 run_pipeline.py --dry-run
# ✅ Works, shows execution plan
```

**Syntax Check:**
```bash
python3 -m py_compile pipeline/export_analytics_to_minio.py run_pipeline.py
# ✅ Both files compile without errors
```

## Technical Details

### JSON Status Communication Protocol
Step 4 outputs JSON marker on stdout:
```
__EXPORT_STATUS_JSON__:{"success": true, "export_status": "minio_success", ...}
```

run_pipeline.py parses this line:
```python
if '__EXPORT_STATUS_JSON__:' in line:
    json_str = line.split('__EXPORT_STATUS_JSON__:')[1]
    extra_data = json.loads(json_str)
```

### ExportStatus Enum Values
```python
ExportStatus.MINIO_SUCCESS.value == 'minio_success'
ExportStatus.MINIO_FAILED.value == 'minio_failed'
ExportStatus.LOCAL_ONLY.value == 'local_only'
ExportStatus.DISABLED.value == 'disabled'
```

These values are used in:
- JSON communication between steps
- Summary message generation
- Test assertions
- Monitoring/alerting integration (future)

---

**Commit:** Fix Step 4 status semantics: proper MinIO status tracking and MINIO_REQUIRED support

This fix ensures that:
1. Step 4 no longer claims success when MinIO fails
2. The text "local + MinIO" only appears when MinIO actually succeeded
3. Users get clear, actionable feedback about what went wrong
4. MINIO_REQUIRED environment variable enables fail-fast behavior when needed
5. Trading can proceed with local signals even if cloud storage fails (unless MINIO_REQUIRED=true)
