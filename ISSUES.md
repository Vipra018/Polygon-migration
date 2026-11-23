# Issues Analysis

> **Summary**: This document outlines the three highest-priority product issues and the three highest-priority backend code issues identified in the Polygon Migration Tool repository, followed by an in-depth code-level Edge Case Analysis.

## Summary

| Type | Critical | High | Medium | Low | Total |
|------|----------|------|--------|-----|-------|
| Product Issues | 1 | 1 | 1 | 0 | 3 |
| Code Issues | 0 | 2 | 1 | 0 | 3 |
| **Total** | **1** | **3** | **2** | **0** | **6** |

---

# Polygon Migration Tool — Issue Analysis

## 1. Product Issues

### P1. The migration workflow does not provide sufficiently clear end-to-end status

**Problem:** Migrating a problem involves multiple separate actions: fetching from Polygon, saving problem metadata, migrating test cases into the database, and uploading test-case files to cloud storage. The user must understand which stage has completed and whether the overall migration is actually usable.

**Impact:** A successful response from one stage can be mistaken for completion of the entire migration. For example, test-case metadata may exist in PostgreSQL even though the corresponding files have not been uploaded. This creates uncertainty and makes it harder to identify where a failed migration needs attention.

**Recommended improvement:** Introduce a visible migration status for each stage, such as `Fetched`, `Database Saved`, `Test Cases Migrated`, `Storage Uploaded`, and `Failed`. Show the result of each operation separately, including the number of records and files processed.

**Priority rationale:** This is the highest-priority product issue because it affects the user's ability to understand whether the primary task has actually succeeded. Clear stage-level feedback also makes failures easier to diagnose.

### P2. Test-case previews do not provide enough confidence in the data being migrated

**Problem:** The test-case migration flow can discard information from the original Polygon data. In particular, input and output values are truncated to 260 characters during the database migration path.

**Impact:** Users may see a preview that does not represent the complete original test case. If the truncated values are later used by the judge or uploaded to storage, the migrated data may not behave like the original Polygon test cases. The user may not notice the loss before completing the migration.

**Recommended improvement:** Preserve complete input and output values. If previews need to be shortened for display, truncate only the rendered preview and provide a way to inspect the full content. Display warnings whenever data is transformed or omitted.

**Priority rationale:** This ranks second because test cases are central to the correctness of the migrated problem. Users need to trust that the data they review is the data the system actually stores and uploads.

### P3. Duplicate problem titles can produce an unhelpful migration failure

**Problem:** The application derives a slug from the problem title. Two different Polygon problems with the same title can therefore generate the same slug, even though they have different Polygon problem IDs.

**Impact:** The second migration can fail with a database uniqueness error. From the user's perspective, two distinct problems are being treated as conflicting records because their titles happen to match. The failure does not provide a useful resolution.

**Recommended improvement:** Generate a unique slug using the title together with the Polygon problem ID, or another stable unique identifier. Catch uniqueness conflicts and return a clear, actionable error to the user.

**Priority rationale:** This ranks third because it prevents certain valid problems from being migrated, but it is narrower in scope than workflow visibility and test-case data integrity.

---

## 2. Backend Code Issues

### C1. Failed Polygon test-case fetches are converted into apparently valid empty data

**Problem:** In `problems/polygon_api.py`, the test-case fetching logic catches exceptions and substitutes empty strings for failed input or output data. The processing loop continues, and the result can be cached in Redis for 30 minutes. Later, the upload logic skips entries with empty data while file numbering is based on list position.

**Impact:**
- A failed request can silently produce an incomplete test-case set.
- Empty values can be cached and reused by later requests.
- Skipped files can create gaps in the uploaded sequence.
- The migration can appear successful even though fewer test cases were uploaded than Polygon provides.

This is particularly dangerous because the failure is not necessarily visible to the user.

**Recommended improvement:**
- Do not convert failed fetches into valid-looking empty test cases.
- Retry transient Polygon API failures with a bounded retry policy.
- Return an explicit failure when required test-case data cannot be fetched.
- Cache only successfully fetched and validated data.
- Compare the expected and successfully processed test-case counts before reporting completion.

**Priority rationale:** This is the highest-priority code issue because it can silently corrupt the migrated dataset. A visible failure is preferable to reporting success with incomplete data.

### C2. Re-migration does not reliably remove obsolete test-case records and files

**Problem:** In `problems/views.py`, the test-case migration loop processes the test cases returned by Polygon in the current fetch. If a problem previously had 20 test cases and now has only 12, the migration updates the 12 returned cases but does not necessarily remove the eight obsolete database records. The storage upload path similarly writes the current sequence without necessarily pruning files left by an earlier, larger migration.

The loop also uses list position to identify records while incrementing the `order` value only for non-empty test cases. This can cause the stored ordering to diverge from the original list positions.

**Impact:**
- Deleted Polygon test cases can remain in PostgreSQL.
- Obsolete files can remain in cloud storage.
- The judge may continue using test cases that the problem setter has removed.
- Database ordering and storage numbering can become inconsistent.

**Recommended improvement:**
- Treat re-migration as reconciliation with the current Polygon dataset, not just an update.
- Use stable test-case identifiers or explicit positions consistently.
- Remove obsolete database records after validating the new dataset.
- Prune obsolete storage objects only after the new upload has succeeded.
- Coordinate database updates and storage changes with a clear rollback strategy.

**Priority rationale:** This ranks second because it creates persistent data-integrity problems across repeated migrations. Unlike a temporary request failure, stale records can continue affecting future evaluations.

### C3. External I/O and migration responsibilities are concentrated in a long-running view

**Problem:** The migration flow performs sequential Polygon API and storage operations from the request-handling path. A problem with many test cases can require a large number of external requests. The flow also keeps database work open while performing potentially slow network operations. In addition, `problems/views.py` contains a very large `index` view that handles multiple responsibilities.

**Impact:**
- Slow external services can keep a web worker occupied for a long time.
- Missing or inadequate request timeouts can cause requests to hang.
- Long-running operations increase the risk of transaction contention.
- A failure late in the process can leave the user waiting after substantial work has already occurred.
- Combining request handling, business logic, database operations, and external integrations makes the code harder to test and extend.

**Recommended improvement:**
- Move long-running migrations into a background job.
- Set explicit connection and read timeouts for external requests.
- Separate Polygon API communication, database persistence, and storage operations into dedicated services.
- Keep database transactions limited to the database operations that need atomicity.
- Add unit tests for each service and integration tests for the complete migration flow.

**Priority rationale:** This ranks third because it primarily affects reliability, scalability, and maintainability. It becomes increasingly important as the number of test cases and concurrent users grows.

---

## 3. Edge Case Analysis

### 1. A problem has zero sample test cases and 15 regular test cases. What happens?

The migration should not assume that sample test cases must exist for regular test cases to be processed. The sample and regular test-case collections are handled separately. With zero samples, the sample collection contributes no entries, while the 15 regular test cases can still be processed.

The important distinction is that the absence of sample cases should not be treated as a failed migration. The resulting database and storage contents should be checked to confirm that all 15 regular cases were preserved.

### 2. A problem is migrated with 20 test cases. The setter later removes eight, leaving 12. What happens when it is migrated again?

The second migration processes the 12 test cases currently returned by Polygon. However, simply updating the returned records does not guarantee that the eight old records are deleted. Similarly, uploading the new sequence does not automatically guarantee that obsolete storage objects are removed.

As a result, stale database records and files may remain. A correct re-migration should reconcile the stored dataset with the latest Polygon dataset and remove obsolete entries safely.

### 3. Two different Polygon problems have the same title, "Two Sum." What happens?

If the application derives the database slug directly from the title, both problems can produce the same slug. If the slug field has a uniqueness constraint, migrating the second problem can fail with an `IntegrityError`.

The underlying problem is that the title is not a unique identifier. The Polygon problem ID should be incorporated into the slug or used as a separate unique identifier.

### 4. What data is intentionally discarded when clicking "Migrate Test Cases to DB"?

The migration path truncates input and output values to 260 characters. This means content beyond that limit is not preserved in the database representation.

This can cause problems when the full test case is required for judging or when the database representation is later used as the source for storage uploads. The full test-case content should be retained; shortening should happen only in the user interface when displaying previews.

---

## 4. Suggested Priority Summary

| Priority | Category | Issue |
|---|---|---|
| P1 | Product | Insufficient end-to-end migration status |
| P2 | Product | Test-case preview and data-fidelity concerns |
| P3 | Product | Duplicate-title migration failure |
| C1 | Code | Silent fetch failures and invalid cached data |
| C2 | Code | Stale database and storage records after re-migration |
| C3 | Code | Blocking external I/O and monolithic view responsibilities |

*Note: File and line references should be checked against the final repository revision before submission. The edge-case descriptions should also be labelled as tested or code-inferred according to the verification actually performed.*
---

## Severity Guidelines

Use these definitions when assigning severity:

| Severity | Definition | Examples |
|----------|------------|----------|
| **Critical** | System broken, security vulnerability, data loss | SQL injection, authentication bypass, data corruption |
| **High** | Major functionality broken, significant data integrity risk | Feature doesn't work, orphaned records, race conditions |
| **Medium** | Feature partially broken, poor UX, code maintainability | Missing validation, confusing errors, code duplication |
| **Low** | Minor issues, cosmetic, best practice violations | Unused imports, inconsistent formatting, missing logs |

---

## Notes

1. **Storage Transaction Journaling**:
   The introduction of `StorageTransaction` in `problems/storage/transaction.py` successfully resolved mid-migration partial upload risks. It snapshots pre-existing bucket objects before overwriting them and guarantees that newly created files are removed on failure without destroying valid existing assets.
2. **Post-Upload Optimization**:
   The cloud upload path in `problems/views.py` was optimized to eliminate 19 redundant Polygon API calls (statement re-fetching, sequential test case downloading, and package extraction) that previously executed after `StorageTransaction.commit()`. Returning immediately upon successful upload reduced round-trip latency from 114 seconds to milliseconds.
3. **Redis Dependency Isolation**:
   Redis caching was designed as an optional acceleration layer for Polygon test case downloads. However, when Redis is offline, calls to `StrictRedis` in `polygon_api.py` block for a 4-second socket timeout. Adding a lightweight connection health check or circuit breaker would enhance local development stability.
