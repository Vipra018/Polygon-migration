# Issues Analysis

> **Summary**: This document outlines the three highest-priority product issues and the three highest-priority backend code issues identified in the Polygon Migration Tool repository, followed by an in-depth code-level Edge Case Analysis.

## Summary

| Type | Critical | High | Medium | Low | Total |
|------|----------|------|--------|-----|-------|
| Product Issues | 1 | 1 | 1 | 0 | 3 |
| Code Issues | 0 | 2 | 1 | 0 | 3 |
| **Total** | **1** | **3** | **2** | **0** | **6** |

---

## Product Issues

### [P1] Stale and Orphaned Test Cases on Polygon Test Case Deletion

**Severity**: Critical

**Location**: `PolygonMigration/problems/views.py:548-581` and `PolygonMigration/problems/polygon_api.py:737-834`

**Description**:
When a problem is re-migrated after a problem setter removes test cases on Polygon, the update loop in `problems/views.py` only iterates from index `0` to `len(test_cases) - 1`. It updates existing records up to the new count but **never deletes** records beyond the new count in PostgreSQL (`ProblemTestCase`). Similarly, the cloud migration routine in `polygon_api.py` uploads objects `1` through `N` into the storage bucket without pruning previously uploaded files.

**Impact**:
- **Data Integrity Violation**: If a problem initially had 20 test cases and the setter removed 8 invalid cases (leaving 12), the database retains all 20 records and cloud storage retains all 40 files.
- **Judge Failures**: Submissions evaluated by an automated online judge will be run against deleted, faulty, or out-of-date test cases.
- **User Confusion**: Staff viewing the problem dashboard see incorrect test case totals and phantom test cases that no longer exist on Polygon.

**Suggested Fix**:
In `problems/views.py`, delete extraneous records after updating the active test cases:
```python
ProblemTestCase.objects.filter(problem=problem_obj, order__gt=len(test_cases)).delete()
```
In `polygon_api.py`, query existing bucket objects for the problem and prune unreferenced paths, or invoke `storage_service.delete_test_cases(problem_id)` within a transaction prior to writing the updated set.

**Priority Rationale**:
This issue is ranked **#1 (Critical)** because it directly corrupts evaluation data and causes online judge grading errors that are invisible to the user without inspecting raw database tables.

---

### [P2] Duplicate Problem Title Causes Hard Unhandled IntegrityError

**Severity**: High

**Location**: `PolygonMigration/problems/views.py:378`, `PolygonMigration/problems/views.py:462`, and `PolygonMigration/problems/models.py:58`

**Description**:
The `Problem` model enforces a global unique constraint on the URL slug: `slug = models.SlugField(unique=True, max_length=255)`. In `views.py`, the slug is generated purely via `slug = slugify(title)`. When a problem is migrated, the lookup key is `Problem.objects.filter(Q(polygon_id=polygon_id)).first()`. If two distinct Polygon problems share the same title (e.g., `"Two Sum"`, `"Array Rotation"`, or `"Maximum Subarray"`), the second problem has a different `polygon_id`, causing the lookup to return `None`. The view then executes `Problem.objects.create(...)` with the identical slug, throwing an unhandled `django.db.utils.IntegrityError: duplicate key value violates unique constraint "problems_problem_slug_key"`.

**Impact**:
- **Migration Blocked**: Any problem with a common or colliding title cannot be migrated into the system.
- **Abrupt Failure**: The entire database transaction aborts with a generic error banner: `"Migration failed and all changes have been rolled back"`, leaving staff with no actionable recourse.

**Suggested Fix**:
Implement automated slug deduplication in `problems/views.py` or within `Problem.save()`:
```python
base_slug = slugify(title) or f"problem-{polygon_id}"
slug = base_slug
counter = 1
while Problem.objects.filter(slug=slug).exclude(polygon_id=polygon_id).exists():
    slug = f"{base_slug}-{counter}"
    counter += 1
```

**Priority Rationale**:
Ranked **#2 (High)** because it is a complete blocker for legitimate problem migrations whenever common algorithmic problem names coincide. It ranks below P1 because P1 causes silent data corruption, whereas P2 fails fast with an explicit error.

---

### [P3] Fragmented, Uncoordinated 4-Step Migration Workflow Lacks Atomic Status

**Severity**: Medium

**Location**: `PolygonMigration/problems/templates/problems/index.html:236-317` and `PolygonMigration/problems/views.py`

**Description**:
The user workflow requires four disconnected, sequential manual steps across three independent HTML forms:
1. Fetch Polygon Data (`#fetchForm`)
2. Create/Update Problem in Database (`#migrate-db-form`)
3. Upload Test Cases to Cloud Storage (`#migrate-azure-form`)
4. Migrate Test Description to Database (`#migrate-test-cases-form`)

There is no workflow coordination, no "Migrate All" single-action option, and no visual badge or checklist indicating which stages have succeeded. If a user runs Step 2 and Step 3 but forgets Step 4, the database lacks test case descriptions. If a user runs Step 3 before Step 2, the button is disabled or aborts with `"Please migrate the problem to the database first"`.

**Impact**:
- **Operational Overhead**: Staff must perform repetitive manual clicks and wait for multiple full-page reloads.
- **Inconsistent Partial State**: Problems frequently end up in partially migrated states (e.g. metadata in DB but files missing from cloud storage, or cloud storage populated but descriptions missing from DB).

**Suggested Fix**:
1. Introduce a unified "One-Click Migration" action that orchestrates metadata migration, test description sync, and cloud upload in a single coordinated pipeline.
2. Add visual status indicators (e.g. "Metadata: Synced", "Database Tests: Synced", "Cloud Storage: 26 Files Uploaded") on the problem dashboard.

**Priority Rationale**:
Ranked **#3 (Medium)** because while it degrades administrator productivity and risks operator error, it does not inherently corrupt data if all four steps are manually executed in the exact prescribed order.

---

## Code Issues

### [C1] Monolithic View Function Violates Single Responsibility Principle

**Severity**: High

**Location**: `PolygonMigration/problems/views.py:88-662` (`index` view, ~575 lines)

**Description**:
The `index` view is a massive "God function" handling:
- HTTP GET and POST parsing.
- Polygon API client initialization and request orchestration.
- HTML package extraction and fallback statement parsing.
- Database CRUD across four separate models (`Problem`, `ProblemTag`, `SampleTestCase`, `ProblemTestCase`).
- Tag creation and relationship reconciliation.
- Cloud storage uploads and transaction handling.
- Redis cache reads, writes, and socket error handling.
- Template context formatting and serialization.

The function has up to 12 levels of indentation, extensive nested `try-except` blocks, and mixed abstractions.

**Technical Impact**:
- **Extreme Fragility**: Changes to one operation (e.g. storage error handling) inadvertently break or delay unrelated flows (such as problem rendering).
- **Untestable Core Logic**: Business rules cannot be unit-tested without mocking the entire Django request lifecycle, session storage, messages framework, and database transactions simultaneously.
- **Maintenance Cost**: High onboarding barrier for new engineers and difficult code reviews.

**Suggested Fix**:
Refactor the view into dedicated service layer modules:
- `ProblemIngestionService`: Handles Polygon API calls and statement parsing.
- `ProblemDatabaseService`: Encapsulates PostgreSQL transactions for problems, tags, and sample tests.
- `ProblemStorageService`: Coordinates cloud storage uploads and transaction boundaries.
The `index` view should merely dispatch requests to the appropriate service and return HTTP responses.

**Priority Rationale**:
Ranked **#1 (High)** under Code Issues because architectural entanglement in `views.py` is the root cause of multiple regression bugs, redundant network calls, and view latency.

---

### [C2] Synchronous Blocking Network I/O Inside Request-Response Cycle

**Severity**: High

**Location**: `PolygonMigration/problems/polygon_api.py:357-410` (`get_all_test_cases`) and `PolygonMigration/problems/polygon_api.py:737-834` (`migrate_to_azure_blob`)

**Description**:
Test cases are fetched from Polygon and uploaded to Supabase Storage sequentially in blocking HTTP loops inside the synchronous Django worker thread. For a problem with 50 test cases, `get_all_test_cases` executes 100 sequential HTTP requests (50 `testInput` + 50 `testAnswer`), followed by 100 sequential HTTP PUT/POST requests to cloud storage. Furthermore, `polygon_api.py` attempts a direct synchronous socket connection to Redis on `localhost:6379` (`polygon_api.py:862`), blocking for a 4-second timeout on every request when Redis is offline.

**Technical Impact**:
- **Thread Starvation**: In a multi-worker production WSGI deployment (Gunicorn / uWSGI), long-running requests hold worker threads hostage for 1–3 minutes, causing worker starvation and denial of service for other users.
- **Gateway Timeouts**: HTTP requests frequently exceed reverse-proxy timeouts (e.g. AWS ALB or Nginx 60-second timeouts), causing HTTP 504 errors while the backend continues orphan processing.

**Suggested Fix**:
1. Offload heavy migrations to a background task queue (Celery, Django-Q, or RQ) with WebSocket or polling updates for task status.
2. In the immediate synchronous path, use connection pooling and concurrent HTTP requests (`concurrent.futures.ThreadPoolExecutor`) for Polygon downloads and cloud uploads.
3. Add a fast connection check or circuit breaker for Redis to eliminate the blocking 4-second timeout when Redis is offline.

**Priority Rationale**:
Ranked **#2 (High)** because blocking synchronous I/O poses an immediate scalability and stability bottleneck for production deployments with multi-test case problem suites.

---

### [C3] Leaky Abstractions and Hardcoded Provider Naming

**Severity**: Medium

**Location**: `PolygonMigration/problems/views.py:125, 195, 227`, `PolygonMigration/problems/polygon_api.py:737, 836`, `PolygonMigration/problems/AzureTestcase.py`, and `PolygonMigration/problems/templates/problems/index.html:250, 253`

**Description**:
While a clean storage abstraction (`BaseStorageService`, `SupabaseStorageService`, `factory.py`) was introduced, the calling layers remain tightly coupled to Azure-specific identifiers and signatures:
- Form fields and view parameters are named `migrate_to_azure`.
- Core API methods are named `migrate_to_azure_blob` and `delete_azure_blob`.
- `api.migrate_to_azure_blob` accepts 6 unused Azure credential arguments (`azure_account_url`, `azure_tenant_id`, etc.) that are ignored when `STORAGE_PROVIDER=supabase`.
- Log statements hardcode messages like `"Uploaded 13 test cases to Azure"`.
- Template form element IDs use `id="migrate-azure-form"`.

**Technical Impact**:
- **Code Confusion**: Developers working on Supabase or AWS S3 integrations must read and maintain methods named `migrate_to_azure_blob`.
- **Fragile Signatures**: Functions carry dead parameters and unused configuration objects across multiple layers.

**Suggested Fix**:
Rename methods and parameters to provider-agnostic equivalents:
- `migrate_to_azure` -> `upload_to_storage`
- `api.migrate_to_azure_blob(...)` -> `api.upload_test_cases_to_storage(problem_id, db_problem_id)`
- Remove provider-specific credential arguments from the Polygon API client signature; let the storage factory resolve provider credentials from `settings.py`.

**Priority Rationale**:
Ranked **#3 (Medium)** because it represents technical debt and architectural friction rather than an active operational failure.

---

## Edge Case Analysis

### Q1: Zero Sample Test Cases and 15 Regular Test Cases

> **Question**: A Polygon problem has 0 sample test cases but 15 regular test cases. What happens when you migrate this problem?

**Exact Code Path & Analysis**:
1. **Fetching Problem Data (`views.py:index`)**:
   - `api.get_all_test_cases` fetches 15 test cases from Polygon via `problem.tests`, `problem.testInput`, and `problem.testAnswer`.
   - In Polygon's API response, each test case has `is_sample: False`.
   - `context['all_test_cases']` receives 15 entries. In `index.html`, the "Sample Test Case" column displays `"No"` for all 15 rows.
2. **Metadata Migration (`migrate_to_db`, `views.py:470-496`)**:
   - The view filters sample cases: `sample_tests = [test for test in test_cases if test.get('is_sample', False)]`.
   - `sample_tests` evaluates to an empty list `[]`.
   - The sample case loop (`for idx, test in enumerate(sample_tests):`) does **not execute**.
   - `SampleTestCase.objects.filter(problem=problem_obj)` has 0 rows created.
   - *Crucial detail*: If this problem was previously migrated with sample test cases, any existing `SampleTestCase` rows are **not deleted** because there is no `.delete()` call.
   - `problem_obj.test_case_count` is set to `15` and saved successfully in PostgreSQL.
3. **Database Test Case Migration (`migrate_test_cases_to_db`, `views.py:548-581`)**:
   - All 15 test cases are processed into `ProblemTestCase` records with `is_sample=False` and truncated 260-byte inputs/outputs.
4. **Cloud Storage Migration (`migrate_to_azure`, `polygon_api.py:737-834`)**:
   - All 15 test cases are uploaded to the bucket under `test_cases/{db_problem_id}/1` through `test_cases/{db_problem_id}/15` (and corresponding `.a` files).
   - Cloud storage does not differentiate sample test cases from system test cases; all 30 objects are stored identically.
5. **Observed Result**:
   The problem migrates successfully without errors. However, student-facing UI views relying on `SampleTestCase` will render the problem statement without example inputs, outputs, or explanations.

---

### Q2: Problem Setter Removes 8 of 20 Test Cases on Polygon

> **Question**: A problem is migrated with 20 test cases. Later, the problem setter removes 8 test cases on Polygon (now 12 remain). The problem is re-migrated. What happens?

**Exact Code Path & Analysis**:
1. **Initial State**:
   - PostgreSQL `ProblemTestCase` contains 20 records (`order` 1 through 20).
   - Cloud Storage contains 40 objects (`test_cases/{id}/1` through `20` and `.a`).
2. **Re-migration to Database (`migrate_test_cases_to_db`, `views.py:548-581`)**:
   - `test_cases` fetched from Polygon now contains 12 items.
   - The view queries: `existing_test_cases = list(ProblemTestCase.objects.filter(problem=problem_obj).order_by('order'))` (length 20).
   - The loop runs: `for idx, test in enumerate(test_cases):` (indices 0 to 11).
   - For `idx` 0 to 11, `existing_test_cases[idx]` is updated with the new test data and saved.
   - **The Defect**: The loop finishes after index 11. Records from index 12 to 19 (`order` 13 through 20) are **never deleted or updated**.
   - **PostgreSQL Outcome**: The database continues to store 20 `ProblemTestCase` records. The first 12 are updated, but the last 8 remain as **orphaned, stale test cases**.
3. **Re-migration to Cloud Storage (`migrate_to_azure`, `polygon_api.py:737-834`)**:
   - `StorageTransaction` uploads new files for test cases 1 through 12.
   - Old storage objects for test cases 13 through 20 (`test_cases/{id}/13` to `20` and `.a`) are **never deleted**.
   - **Cloud Storage Outcome**: The bucket retains 40 files (24 current, 16 stale).
4. **Observed Result**:
   Re-migration fails to achieve parity with Polygon. Stale, deleted test cases persist indefinitely in both PostgreSQL and Cloud Storage, causing automated judge runners to evaluate submissions against obsolete test cases.

---

### Q3: Two Different Polygon Problems Have the Exact Same Title: "Two Sum"

> **Question**: Two different Polygon problems have the exact same title: "Two Sum". You migrate the first one successfully. Then you try to migrate the second one. What happens?

**Exact Code Path & Analysis**:
1. **First Problem Migration**:
   - Polygon ID: `1001`, Title: `"Two Sum"`.
   - `slug = slugify("Two Sum")` -> `"two-sum"`.
   - `Problem.objects.filter(Q(polygon_id="1001")).first()` returns `None`.
   - `Problem.objects.create(polygon_id="1001", title="Two Sum", slug="two-sum", ...)` succeeds.
   - Database stores ID `1` with `slug="two-sum"` and `polygon_id="1001"`.
2. **Second Problem Migration**:
   - Polygon ID: `2002`, Title: `"Two Sum"`.
   - `slug = slugify("Two Sum")` -> `"two-sum"`.
   - The lookup in `views.py:434`:
     ```python
     problem_obj = Problem.objects.filter(Q(polygon_id="2002")).first()
     ```
     Because Polygon ID `2002` does not exist in the database, `problem_obj` evaluates to `None`.
   - The view enters the `else:` branch at `views.py:460`:
     ```python
     problem_obj = Problem.objects.create(
         polygon_id="2002",
         title="Two Sum",
         slug="two-sum",
         ...
     )
     ```
3. **Database Failure**:
   - The `Problem` model specifies `slug = models.SlugField(unique=True, max_length=255)`.
   - PostgreSQL encounters a collision on the `problems_problem_slug_key` unique index.
   - PostgreSQL raises:
     ```text
     django.db.utils.IntegrityError: duplicate key value violates unique constraint "problems_problem_slug_key"
     DETAIL: Key (slug)=(two-sum) already exists.
     ```
4. **Transaction Rollback & User View**:
   - Because `migrate_to_db` runs inside `with transaction.atomic():`, the atomic transaction rolls back all pending inserts.
   - The exception is caught by `views.py:585`:
     ```python
     context['error'] = f"Migration failed and all changes have been rolled back. Reason: {str(e)}"
     ```
   - The user sees a red alert banner declaring that the migration failed due to a database integrity error. The second problem is completely blocked from migrating until its title or slug is changed.

---

### Q4: Data Intentionally Discarded During "Migrate Test Cases to DB"

> **Question**: When test cases are saved to the database via "Migrate Test Cases to DB", some data is intentionally discarded. What data is lost? Why might this cause problems?

**Exact Code Path & Analysis**:
1. **What Data Is Discarded**:
   In `PolygonMigration/problems/views.py:557-560`:
   ```python
   # Truncate input and output to first 260 bytes
   truncated_input = input_data[:260]
   truncated_output = output_data[:260]
   ```
   For every test case, any character in `input_data` and `output_data` beyond the **first 260 characters** is permanently discarded when creating or updating `ProblemTestCase` records in PostgreSQL.
2. **Why This Was Implemented**:
   Competitive programming test cases regularly reach 10 MB to 50 MB in size (e.g. arrays of $10^5$ integers, large trees, dense graphs). Storing hundreds of multi-megabyte test cases directly in PostgreSQL rows would rapidly bloat database storage, degrade query performance, and exhaust RAM during Django ORM serialization. `ProblemTestCase` was designed purely as an administrative preview table for the Django dashboard.
3. **Why This Causes Problems**:
   - **Judge Evaluation Failure**: If an engineer, runner service, or automated script queries `ProblemTestCase` expecting to run local testing or judge execution from the database, the inputs will be truncated, syntactically malformed, and invalid.
   - **False Sense of Backup**: Operators may mistakenly believe that clicking "Migrate Test Cases to DB" backed up the test suite. If cloud storage is lost or unpopulated, the full test data cannot be recovered from PostgreSQL.
   - **UI Discrepancy**: While the in-memory view displays full data if available from the Polygon fetch context, reloading the problem from the database only displays the 260-byte truncated snippet, preventing staff from reviewing the complete test case in the UI.

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
