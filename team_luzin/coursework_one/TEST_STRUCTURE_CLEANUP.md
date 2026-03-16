# Test File Structure Cleanup

## Summary
Reorganized test files to use cleaner, more professional module-oriented naming. Removed historical suffixes that added no clarity.

**Status**: ✅ Complete - All 494 tests passing, coverage stable at 81%

---

## Renaming Mapping

### 1. Portfolio Selection Tests
**Before**: `test_composite_scoring_smoke.py` (35 tests)
**After**: `test_composite_scoring.py`
**Rationale**: "Smoke" suffix is vague and unnecessary for a main module test file

### 2. Signal Generation Tests
**Before**:
- `test_execution_signals_unit.py` (20 tests)
- `test_execution_signals_smoke.py` (26 tests)

**After**:
- `test_execution_signals.py` (20 tests - unit tests)
- `test_execution_signals_integration.py` (26 tests - integration/smoke tests)

**Rationale**:
- Unit tests are "default" - "_unit" suffix is redundant
- "Smoke" → "integration" is clearer for broader test scope
- Clear separation of unit vs. integration concerns

### 3. MinIO Diagnostics Tests
**Before**: `test_minio_diagnostics_unit.py` (18 tests)
**After**: `test_minio_diagnostics.py`
**Rationale**: "_unit" is redundant; this is the main test file

### 4. Output Reader Tests
**Before**: `test_output_reader_edge_cases.py` (7 tests)
**After**: `test_output_reader.py`
**Rationale**: Error handling can be documented in docstring, not filename; cleaner naming

### 5. Pipeline Structured Types Tests
**Before**: `test_pipeline_refactor.py` (25 tests)
**After**: `test_pipeline_modules.py`
**Rationale**: "_refactor" is historical. File tests structured pipeline modules (StepResult, PipelineRunSummary, ExportStatus)

### 6. Pipeline Orchestration Tests
**Before**:
- `test_run_pipeline_smoke.py` (38 tests)
- `test_run_pipeline_integration.py` (21 tests)

**After**:
- `test_run_pipeline.py` (38 tests - main runner tests)
- `test_run_pipeline_orchestration.py` (21 tests - orchestration/status tests)

**Rationale**:
- "Smoke" removed from main/default test file
- "Orchestration" clarifies that this file tests high-level status tracking and coordination logic

---

## Unchanged Files

These files retained their original names (already professional/module-oriented):
- `test_coverage_boost.py` - Coverage improvement tests
- `test_datalake_writer.py` - Data lake storage
- `test_liquidity.py` - Liquidity calculations
- `test_minio_storage.py` - MinIO storage layer
- `test_momentum.py` - Momentum indicators
- `test_parquet_reader.py` - Parquet file reading
- `test_pipeline_integration.py` - Full pipeline integration tests
- `test_postgres_connector.py` - Database connections
- `test_price_extractor.py` - Price data extraction
- `test_risk.py` - Risk calculations
- `test_sector_filter.py` - Sector filtering
- `test_trend.py` - Trend indicators

---

## Naming Conventions Applied

### Pattern: `test_<module>.py`
- **Default test file** for a module
- Contains primary unit tests and core functionality tests
- Examples: `test_composite_scoring.py`, `test_minio_diagnostics.py`, `test_output_reader.py`

### Pattern: `test_<module>_integration.py`
- **Integration/broader tests** for a module
- Tests workflows, end-to-end scenarios, system interactions
- Examples: `test_execution_signals_integration.py`

### Pattern: `test_<module>_orchestration.py`
- **Orchestration-focused tests** for a module
- Tests high-level coordination, status tracking, control flow
- Examples: `test_run_pipeline_orchestration.py`

### Removed Suffixes
- ❌ `_smoke` - Vague term, replaced with "_integration" where applicable
- ❌ `_unit` - Redundant, unit tests are the default
- ❌ `_refactor` - Historical, replaced with descriptive names
- ❌ `_edge_cases` - Narrow descriptor, documented in docstring instead

---

## Validation Results

✅ **All 494 tests passing**
```
✅ PASS - test_composite_scoring.py (35 tests)
✅ PASS - test_execution_signals.py (20 tests)
✅ PASS - test_execution_signals_integration.py (26 tests)
✅ PASS - test_minio_diagnostics.py (18 tests)
✅ PASS - test_output_reader.py (7 tests)
✅ PASS - test_pipeline_modules.py (25 tests)
✅ PASS - test_run_pipeline.py (38 tests)
✅ PASS - test_run_pipeline_orchestration.py (21 tests)
```

✅ **Coverage stable at 81%** (5123/6334 statements covered)

✅ **No production code changes** - Only test file renaming

✅ **Pytest discovery working** - All files properly named and discoverable

---

## Benefits

1. **Professional appearance** - No historical suffixes or vague naming
2. **Clear structure** - Module-oriented naming makes purpose obvious
3. **Easier navigation** - Less ambiguity about what each file tests
4. **Reduced cognitive load** - Developers understand scope at a glance
5. **Maintainability** - Future test additions follow clear naming pattern
6. **Zero risk** - No code changes, only rename operations

---

## Migration Notes

If you have any local references to old test file names (e.g., in CI/CD, documentation, or scripts), update them to use the new names. Python imports were not affected as tests don't import from each other.

### Example Updates
- `pytest test_execution_signals_unit.py` → `pytest test_execution_signals.py`
- `pytest test_run_pipeline_smoke.py` → `pytest test_run_pipeline.py`
- Documentation references updated in this file

