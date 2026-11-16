# Polygon Migration Tool — Onboarding & Architecture Documentation

## 1. Project Overview

### Purpose
The **Polygon Migration Tool** (internally designated **Hatsu**) is a Django-based engineering portal built for competitive programming platforms (such as AlgoUniversity / Algopath). Its primary purpose is to automate the ingestion, synchronization, and cloud distribution of competitive programming problems authored on [Codeforces Polygon](https://polygon.codeforces.com/).

The tool bridges the Polygon content authoring system with the production database and judge evaluation environment by:
1. Authenticating with the Polygon REST API via cryptographic SHA-512 signatures.
2. Ingesting problem statements, constraints, memory/time limits, tags, difficulty, solutions, and custom checkers.
3. Synchronizing structured metadata into a relational PostgreSQL database.
4. Uploading complete, un-truncated test case suites (inputs and expected outputs) to cloud object storage for judge execution.

### Technology Stack
- **Framework**: Django 5.2.3 (Python 3.11.9)
- **Relational Database**: PostgreSQL (hosted on Neon Serverless PostgreSQL)
- **Object Storage**: Pluggable architecture supporting **Supabase Storage** (default active provider) and **Azure Blob Storage**
- **Caching Layer**: Redis (optional caching for raw Polygon test case inputs/outputs)
- **Frontend**: Django Templates, Bootstrap 5, Vanilla JavaScript, CSS3
- **HTTP Client**: Python `requests` library

### High-Level Architecture
```
                         +-----------------------------------+
                         |      Codeforces Polygon API       |
                         |  (problem.info, statements, tests)|
                         +-----------------+-----------------+
                                           |
                                 PolygonAPI Client
                           (SHA-512 Request Signing)
                                           |
                                           v
+------------------+             +-------------------+             +-----------------------+
|  Staff Browser   | <=========> | Django Controller | <=========> | Neon PostgreSQL DB    |
|  (Bootstrap UI)  |  HTTP POST  |  (problems/views) |   ORM / SQL | (Problem, Tags, Tests)|
+------------------+             +---------+---------+             +-----------------------+
                                           |
                             get_storage_service(provider)
                                           |
                                           v
                              +-------------------------+
                              |   StorageTransaction    |
                              |  (Journaled Rollback)   |
                              +------------+------------+
                                           |
                   +-----------------------+-----------------------+
                   |                                               |
                   v                                               v
     +---------------------------+                   +---------------------------+
     |  SupabaseStorageService   |                   |    AzureStorageService    |
     | (REST API / Bearer Auth)  |                   | (Azure Blob SDK / Shared) |
     | Bucket: polygon-testcases |                   |  Container: testcases     |
     +---------------------------+                   +---------------------------+
```

### Database vs. Cloud Storage Responsibilities
To maintain database performance and prevent operational bloat while supporting high-throughput online judges, data responsibilities are strictly separated:

| Responsibility | Neon PostgreSQL Database | Supabase Cloud Object Storage |
| :--- | :--- | :--- |
| **Problem Metadata** | Full problem record: title, slug, statement, input/output formats, constraints, editorial, notes, time/memory limits, checker type, difficulty. | None. |
| **Tags & Taxonomy** | `ProblemTag` M2M relations for categorization and search. | None. |
| **Sample Test Cases** | `SampleTestCase` table stores full sample inputs and outputs for direct rendering in problem statements. | Also uploaded as regular numbered test cases in storage. |
| **System Test Cases** | `ProblemTestCase` table stores **metadata only** (order, is_sample flag, description) and input/output previews truncated to 260 bytes for administrative browsing. | **Complete, unmodified test cases** (up to tens of megabytes per file) stored as raw bytes for online judge execution. |
| **Checkers** | Checker type identifier (`wcmp`, `ncmp`, etc.) and custom checker name. | Compiled custom checker binaries (e.g. `check.exe`) or source files. |

---

## 2. Setup and Configuration

### Requirements
- **Python**: 3.11.x or higher
- **Virtual Environment**: Standard virtual environment (`venv`)
- **PostgreSQL**: Neon PostgreSQL instance or local PostgreSQL 14+
- **Redis**: Optional local or remote Redis instance (host default: `localhost:6379`)

### Environment Variables (`.env`)
The application is configured using a `.env` file located in `PolygonMigration/.env`. The table below lists all required variables without exposing actual production secrets:

| Variable | Description | Example / Allowed Values |
| :--- | :--- | :--- |
| `SECRET_KEY` | Django cryptographic secret key | Django secret key string |
| `DEBUG` | Django debug mode | `True` or `False` |
| `DB_NAME` | PostgreSQL database name | e.g. `neondb` |
| `DB_USER` | PostgreSQL username | e.g. `neondb_owner` |
| `DB_PASSWORD` | PostgreSQL password | Database user password |
| `DB_HOST` | PostgreSQL host address | e.g. `ep-blue-frog-*.aws.neon.tech` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `POLYGON_API_KEY` | Polygon API Key for request authentication | Polygon API key |
| `POLYGON_API_SECRET` | Polygon API Secret for SHA-512 signing | Polygon API secret |
| `STORAGE_PROVIDER` | Cloud storage adapter selector | `supabase` (active) or `azure` |
| `SUPABASE_URL` | Supabase project API base URL | `https://<project-ref>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase `service_role` secret key | Supabase service_role JWT token |
| `SUPABASE_STORAGE_BUCKET` | Supabase private storage bucket name | `polygon-testcases` |
| `AZURE_STORAGE_ACCOUNT_URL` | Azure Blob Storage account endpoint | `https://<account>.blob.core.windows.net/` |
| `AZURE_TENANT_ID` | Azure Active Directory Tenant ID | Azure Tenant UUID |
| `AZURE_CLIENT_ID` | Azure Service Principal Client ID | Azure Client UUID |
| `AZURE_USERNAME` | Azure Storage username / principal | Azure username |
| `AZURE_PASSWORD` | Azure Storage password / principal secret | Azure secret |
| `AZURE_CONTAINER_NAME` | Azure Blob Container name | `testcases` |
| `REDIS_HOST` | Redis cache hostname | `localhost` or remote host |
| `REDIS_PORT` | Redis cache port | `6379` |
| `REDIS_PASSWORD` | Redis password (if authentication enabled) | Redis password |
| `REDIS_SSL` | Enable TLS/SSL for Redis connections | `False` or `True` |

> [!CAUTION]
> Never commit actual API keys, database passwords, or `SUPABASE_SERVICE_ROLE_KEY` into version control. Ensure `PolygonMigration/.env` is ignored by `.gitignore`.

### Initial Setup Commands

1. **Activate Virtual Environment**:
   ```powershell
   # Windows PowerShell
   .\venv\Scripts\Activate.ps1
   ```

2. **Install Dependencies**:
   ```powershell
   pip install -r requirement.txt
   ```

3. **Verify Configuration & Run System Checks**:
   ```powershell
   python PolygonMigration\manage.py check
   ```

4. **Apply Database Migrations**:
   ```powershell
   python PolygonMigration\manage.py migrate
   ```

5. **Start Development Server**:
   ```powershell
   python PolygonMigration\manage.py runserver 127.0.0.1:8000
   ```

---

## 3. Application Architecture

### Django Apps
1. **`users`**:
   - Custom user model (`users.User`) inheriting from `AbstractBaseUser` and `PermissionsMixin`.
   - Email-based authentication backend (`users.backends.EmailBackend`).
   - Views for staff login and session termination.
2. **`problems`**:
   - Core problem migration engine, data models, template views, and cloud storage adapters.
3. **`contents`**:
   - Educational curriculum taxonomy models (`Topic`, `SubTopic`, etc.) linked to migrated problems.

### Core Data Models (`problems/models.py`)
- **`Problem`**: The central record representing a competitive programming challenge.
  - `polygon_id` (`CharField`, unique): Polygon Problem ID (e.g. `"631622"`).
  - `title` (`CharField`), `slug` (`SlugField`, unique): URL-friendly identifier.
  - `difficulty` (`CharField`): Choices: `easy`, `medium`, `hard`.
  - `problem_statement`, `input_format`, `output_format`, `constraints`, `editorial`, `notes`: Problem text content.
  - `time_limit` (`FloatField`, ms), `memory_limit` (`IntegerField`, MB).
  - `checker_type` (`CharField`): e.g. `ncmp`, `wcmp`, `rcmp6`, or `custom`.
  - `test_case_count` (`IntegerField`): Total count of tests on Polygon.
  - `extra_tags` (`ManyToManyField` to `ProblemTag`): Taxonomical tags.
- **`SampleTestCase`**: Sample cases rendered directly in the problem description.
  - `problem` (`ForeignKey` to `Problem`), `input` (`TextField`), `output` (`TextField`), `order` (`IntegerField`).
- **`ProblemTestCase`**: Administrative test case descriptors.
  - `problem` (`ForeignKey`), `is_sample` (`BooleanField`), `input` (`TextField`, truncated to 260 bytes), `output` (`TextField`, truncated to 260 bytes), `description` (`TextField`), `order` (`IntegerField`).
- **`ProblemTag`**: Reusable tags for problems.

### Storage Abstraction Architecture (`problems/storage/`)
The cloud storage subsystem decouples Django views and Polygon API routines from specific cloud vendors:

```
                  BaseStorageService (ABC)
                  ├── get_input_path(problem_id, test_num)  -> test_cases/{id}/{num}
                  ├── get_output_path(problem_id, test_num) -> test_cases/{id}/{num}.a
                  ├── upload_test_case(...)
                  ├── download_test_case(...)
                  ├── test_case_exists(...)
                  ├── delete_test_cases(...)
                  ├── upload_file(...) / download_file(...)
                  └── file_exists(...) / delete_file(...)
                               ▲
                               │
            +------------------+------------------+
            |                                     |
   AzureStorageService                   SupabaseStorageService
  (Azure Blob SDK / REST)               (Supabase Storage REST API)
```

- **`BaseStorageService` (`problems/storage/base.py`)**: Abstract base class defining the required storage contract and relative path conventions:
  - Input: `test_cases/{problem_id}/{test_number}`
  - Output: `test_cases/{problem_id}/{test_number}.a`
  - Custom Checker: `test_cases/{problem_id}/{filename}`
- **`SupabaseStorageService` (`problems/storage/supabase.py`)**: Production-ready adapter communicating with Supabase Storage REST API (`/storage/v1/object/...`) using standard authenticated HTTP calls with Bearer `service_role` credentials.
- **`AzureStorageService` (`problems/storage/azure.py`)**: Adapter maintaining full compatibility with Microsoft Azure Blob Storage.
- **`AzureBlobManager` (`problems/AzureTestcase.py`)**: Backward-compatible subclass alias of `AzureStorageService`.
- **`get_storage_service(provider=None)` (`problems/storage/factory.py`)**: Factory method selecting the appropriate adapter based on `STORAGE_PROVIDER`.

### StorageTransaction & Rollback Behavior (`problems/storage/transaction.py`)
To prevent orphaned or corrupted files during network failures or mid-upload exceptions, all cloud mutations execute inside a **`StorageTransaction`**:
1. **Pre-flight Snapshotting**: Prior to overwriting any existing object in the bucket, `StorageTransaction` downloads and buffers its original bytes in memory (`self.backups[path]`).
2. **New File Tracking**: Files created for the first time during the transaction are recorded in `self.created_files`.
3. **Atomic Commit**: If all test cases and checker files succeed, `transaction.commit()` clears the backups and preserves the new state.
4. **Non-Destructive Rollback**: If an exception occurs:
   - Newly created files during this attempt are deleted (`self.storage.delete_file`).
   - Pre-existing files that were modified are restored byte-for-byte to their original content (`self.storage.upload_file(path, original_data)`).
   - Valid, pre-existing files from earlier successful uploads are **never deleted**.

---

## 4. Detailed Walkthrough of Required User Flows

### Flow A: User Login
- **User Action**: The user visits `http://127.0.0.1:8000/users/login/`, enters their email and password, and clicks **Login**.
- **Frontend Parameters**:
  - `csrfmiddlewaretoken`: CSRF token string.
  - `email`: User email address.
  - `password`: User password.
- **Django Routing**: `PolygonMigration/urls.py` -> `users/urls.py` -> `users.views.login_view`.
- **Execution Order**:
  1. `users.views.login_view` receives `POST`.
  2. Calls `django.contrib.auth.authenticate(request, username=email, email=email, password=password)`.
  3. `users.backends.EmailBackend.authenticate` queries `UserModel.objects.get(email=email)`.
  4. Validates password via `user.check_password(password)` and verifies `user_can_authenticate(user)`.
  5. Checks staff authorization: `if user.is_staff:`. Non-staff users are rejected with `"You do not have staff access."`.
  6. Calls `django.contrib.auth.login(request, user)` to establish the session.
- **Database Reads/Writes**: Reads `users_user` table. Writes new session to `django_session` table.
- **External Calls / Storage / Redis**: None.
- **User Experience**: Redirected to `problems:index` (`/`), presenting the Hatsu problem migration dashboard.

---

### Flow B: Fetching a Polygon Problem
- **User Action**: User enters a Polygon Problem ID (e.g. `631622`) in the input box and clicks **Fetch Problem Data**.
- **Frontend Parameters**:
  - `problem_id`: String (e.g. `'631622'`).
  - `csrfmiddlewaretoken`: CSRF token string.
- **Django Routing**: `PolygonMigration/urls.py` -> `problems/urls.py` -> `problems.views.index`.
- **Execution Order**:
  1. `views.index` normalizes problem ID: `polygon_id = (request.POST.get('problem_id') or '').strip()`. Rejects empty input with `"Please enter a valid Polygon Problem ID."`.
  2. Queries `Problem.objects.filter(polygon_id=polygon_id).first()` to check if the problem was previously migrated to PostgreSQL.
  3. If found in DB, extracts attached tags, difficulty, and fetches the main solution from Polygon API (`problem.updateWorkingCopy`, `problem.solutions`, `problem.viewSolution`).
  4. Calls `api.get_problem_info(polygon_id)` (`problem.info` endpoint).
  5. Attempts package download via `api.download_and_extract_package(polygon_id)`. If no compiled package exists on Polygon, falls back to `api.get_statements(polygon_id)` (`problem.statements` endpoint) to parse title, statement, input/output formats, and notes.
  6. Checks Redis for cached test cases via `api.get_test_cases_from_redis(polygon_id)`.
  7. On Redis miss, calls `api.get_all_test_cases(polygon_id)`:
     - Calls `problem.tests` to list all test case indices and sample flags.
     - Iterates over each test case index, calling `problem.testInput` and `problem.testAnswer` sequentially.
     - Attempts to cache the retrieved test cases in Redis via `api.store_test_cases_in_redis`.
  8. Checks checker type via `problem.checker` and custom checker details via `problem.files`.
  9. Builds `context['fetched_problem']` and `context['all_test_cases']` (with 50-character previews).
- **External API Calls**:
  - `problem.info`, `problem.statements` (or package download), `problem.tests`, `problem.testInput` (per test), `problem.testAnswer` (per test), `problem.checker`, `problem.files`.
- **Database Reads/Writes**: Read `Problem`, `ProblemTag`. No database writes.
- **Storage / Redis**: No cloud storage operations. Reads/writes Redis test case cache key `test_cases_{polygon_id}`.
- **User Experience**: The page renders problem title, metadata table, problem statement legend, input/output format cards, action buttons, and a table listing all test cases with full content inspection modals.

---

### Flow C: Migrating Problem Metadata to PostgreSQL
- **User Action**: User selects a difficulty (e.g. `Easy`), searches/selects tags or adds a new tag, and clicks **Create/Update problem in Database**.
- **Frontend Parameters**:
  - `problem_id`: String (e.g. `'631622'`).
  - `migrate_to_db`: `'1'`.
  - `difficulty`: String (`easy`, `medium`, or `hard`).
  - `tags`: List of tag names.
  - `new_tag`: Optional custom tag string.
- **Django Routing**: `problems.views.index` (inside `with transaction.atomic():`).
- **Execution Order**:
  1. Validates that `difficulty` is provided; raises error if missing.
  2. Queries `Problem.objects.filter(Q(polygon_id=polygon_id)).first()`.
  3. If existing record found: updates `title`, `slug`, `difficulty`, `problem_statement`, `input_format`, `output_format`, `time_limit`, `memory_limit`, `checker_type`, `test_case_count`, `notes`.
  4. If not found: creates new `Problem` record via `Problem.objects.create(...)`.
  5. Clears and re-associates tags using `problem_obj.extra_tags.clear()` and `ProblemTag.objects.get_or_create(...)`.
  6. Retrieves test cases from Redis (or falls back to Polygon API).
  7. Filters tests where `is_sample=True`. For each sample test case, updates or creates a `SampleTestCase` record with `problem=problem_obj`, `input=input_data`, `output=output_data`, `order=order`.
  8. Sets `context['db_success'] = "Problem '{title}' updated in database successfully."`.
- **Database Reads/Writes**: Reads and writes `problems_problem`, `problems_problemtag`, `problems_problem_extra_tags`, and `problems_sampletestcase`.
- **External Calls / Storage / Redis**: Reuses cached test cases from Redis if available. No cloud storage operations.
- **User Experience**: Blue alert banner `"Problem 'Array Rotation' updated in database successfully."` appears. Database Problem ID and clickable Algopath link (`https://www.algopath.ai/problems/array-rotation`) appear in the table. The "Upload Test Cases to Cloud Storage" button becomes enabled.

---

### Flow D: Migrating Test Cases to PostgreSQL
- **User Action**: User clicks **Migrate Test Description to Database**.
- **Frontend Parameters**:
  - `problem_id`: String (e.g. `'631622'`).
  - `migrate_test_cases_to_db`: `'1'`.
- **Django Routing**: `problems.views.index` (inside `with transaction.atomic():`).
- **Execution Order**:
  1. Checks if problem exists in database: `Problem.objects.filter(polygon_id=polygon_id).first()`. If not found, aborts with `"Please migrate the problem to the database first."`.
  2. Fetches test cases from Redis (or Polygon API fallback).
  3. Queries `existing_test_cases = list(ProblemTestCase.objects.filter(problem=problem_obj).order_by('order'))`.
  4. Loops through each test case:
     - Extracts `input` and `output` strings.
     - **Truncates** input and output to the first 260 characters (`truncated_input = input_data[:260]`, `truncated_output = output_data[:260]`).
     - If index exists in `existing_test_cases`, updates fields; otherwise calls `ProblemTestCase.objects.create(...)`.
  5. Sets `context['success'] = "Test cases description migrated to database Successfully."`.
- **Database Reads/Writes**: Reads `Problem`; reads, updates, and creates `ProblemTestCase` rows.
- **External Calls / Storage / Redis**: Reads Redis cache. No cloud storage operations.
- **User Experience**: Green alert banner `"Test cases description migrated to database Successfully."` appears.

---

### Flow E: Uploading Test Cases to Cloud Storage
- **User Action**: User clicks **Upload Test Cases to Cloud Storage**.
- **Frontend Parameters**:
  - `problem_id`: String (e.g. `'631622'`).
  - `migrate_to_azure`: `'1'`.
- **Django Routing**: `problems.views.index` -> `PolygonAPI.migrate_to_azure_blob`.
- **Execution Order**:
  1. Client-side JavaScript displays `#loadingOverlay` with `"Uploading to Supabase Storage..."`.
  2. `views.index` verifies `Problem` exists in PostgreSQL. Extracts `problem_id = problem_obj.id` (database ID `1`).
  3. Checks for custom checker via `api.get_custom_checker_info(polygon_id)`.
  4. Calls `api.migrate_to_azure_blob(...)`.
  5. Inside `migrate_to_azure_blob`:
     - Fetches all test cases (from Redis or Polygon).
     - Obtains active storage adapter via `get_storage_service()` (`SupabaseStorageService`).
     - Initializes `transaction = StorageTransaction(storage_service)`.
     - Loops through test cases $1 \dots N$. For each case, calls:
       `transaction.upload_test_case(db_problem_id, idx, input_data, output_data)`:
       - Uploads input to `test_cases/{db_problem_id}/{idx}`.
       - Uploads output to `test_cases/{db_problem_id}/{idx}.a`.
     - If custom checker exists, compiles it and uploads binary via `transaction.upload_file`.
     - Commits the storage transaction: `transaction.commit()`.
     - Returns `test_cases` list to `views.index`.
  6. **Optimized Return Path**:
     - `views.index` builds `context['all_test_cases']` directly from returned `test_cases`.
     - Populates `context['fetched_problem']` directly from existing `problem_obj`.
     - Sets `context['success'] = "Test cases uploaded to Supabase Storage successfully."`.
     - Returns `render(request, 'problems/index.html', context)` **immediately**, eliminating all redundant post-upload Polygon API calls.
- **Database Reads/Writes**: Reads `Problem`.
- **Cloud Storage Reads/Writes**:
  - Uploads 26 objects (13 inputs, 13 outputs) directly to Supabase private bucket `polygon-testcases`.
- **User Experience**: Screen immediately updates with green success alert `"Test cases uploaded to Supabase Storage successfully."`, showing the full problem details and test cases table.

---

## 5. Polygon API Integration

### Cryptographic Request Signing (SHA-512)
The Polygon API requires all authenticated POST endpoints to include `apiKey`, `time`, and `apiSig` parameters. The cryptographic signing process implemented in `PolygonAPI._generate_api_sig` (`problems/polygon_api.py:35-69`) works as follows:

1. **Timestamp**: Generates the current UNIX epoch time in seconds (`params['time'] = int(time.time())`).
2. **Key Injection**: Sets `params['apiKey'] = self.api_key`.
3. **Lexicographical Sorting**: Sorts all request parameters alphabetically by key:
   ```python
   sorted_params = sorted(params.items())
   ```
4. **URL Encoding**: Converts sorted pairs to an application/x-www-form-urlencoded query string:
   ```python
   param_str = urlencode(sorted_params)
   ```
5. **Random Prefix**: Generates a 6-character random alphanumeric salt string (`rand_prefix`), e.g. `"abcdef"`.
6. **Hash String Construction**: Concatenates salt, endpoint name, query string, and API secret:
   ```
   {rand_prefix}/{method_name}?{param_str}#{self.api_secret}
   ```
7. **SHA-512 Hash**: Computes SHA-512 digest encoded in UTF-8:
   ```python
   sha512_hash = hashlib.sha512(to_hash.encode('utf-8')).hexdigest()
   ```
8. **Final Signature**: Prepends the salt prefix to the hash digest:
   ```python
   api_sig = f"{rand_prefix}{sha512_hash}"
   ```

### Endpoints Used in Implementation
- **`problem.info`**: Fetches problem limits and constraints (`timeLimit`, `memoryLimit`, `inputFile`, `outputFile`, `interactive`).
- **`problem.packages` & `problem.package`**: Lists and downloads the standard problem archive (`problem.html` and assets).
- **`problem.statements`**: Fallback endpoint retrieving localized problem text (`legend`, `input`, `output`, `notes`).
- **`problem.tests`**: Lists test cases in testset, indicating sample case flags (`manual`, `is_sample`).
- **`problem.testInput`**: Fetches raw, unmodified input data for an individual test case.
- **`problem.testAnswer`**: Fetches raw, unmodified expected output data for an individual test case.
- **`problem.checker`**: Identifies standard or custom checker name (e.g. `std::wcmp.cpp`).
- **`problem.files`**: Lists resource and source files in the Polygon working copy.
- **`problem.viewFile`**: Retrieves raw source code for custom checkers.
- **`problem.updateWorkingCopy`**: Synchronizes Polygon working copy before inspecting solutions.
- **`problem.solutions` & `problem.viewSolution`**: Locates and retrieves the reference correct solution (`MA` tag).

---

## 6. Cloud Storage Integration

### Supabase Storage Provider
Due to the absence of active Azure subscriptions, Supabase Storage was integrated as a secure, S3-compatible cloud object store:
- **Bucket**: `polygon-testcases` (configured as **PRIVATE**).
- **Authentication**: Authenticated via standard HTTP headers containing the secret `service_role` key:
  ```http
  Authorization: Bearer <SUPABASE_SERVICE_ROLE_KEY>
  apikey: <SUPABASE_SERVICE_ROLE_KEY>
  ```
- **Direct REST Communication**: Calls Supabase Storage API endpoints directly:
  - Upload: `POST {SUPABASE_URL}/storage/v1/object/{bucket}/{path}` with `x-upsert: true`.
  - Download: `GET {SUPABASE_URL}/storage/v1/object/authenticated/{bucket}/{path}`.
  - Delete: `DELETE {SUPABASE_URL}/storage/v1/object/{bucket}` with payload `{"prefixes": [path]}`.
  - Exists: `POST {SUPABASE_URL}/storage/v1/object/list/{bucket}`.

### Standard Object Path Structure
To ensure universal judge compatibility, all test case files adhere strictly to the unpadded structure:
- **Input File**: `test_cases/{db_problem_id}/{test_number}`
- **Output File**: `test_cases/{db_problem_id}/{test_number}.a`

> [!IMPORTANT]
> The implementation strictly uses the **PostgreSQL database Problem ID** (`problem_obj.id`), **NOT** the Polygon ID, for the `{problem_id}` directory segment. This matches the database foreign key relationships expected by online judge runners.

---

## 7. Database vs. Cloud Storage Matrix

| Artifact / Entity | Neon PostgreSQL Storage | Supabase Object Storage | Notes |
| :--- | :---: | :---: | :--- |
| Problem Title, Slug, Difficulty | Yes | No | Relational query indices |
| HTML Statement, Notes, Limits | Yes | No | Rendered in problem view |
| Associated Tags | Yes | No | M2M relationship |
| Sample Test Cases | Yes | Yes | DB holds full text for statement rendering; cloud holds numbered files |
| Regular Test Case Previews | Yes (truncated to 260 bytes) | No | DB acts as preview catalog |
| Full Test Case Inputs (System) | No | Yes (raw bytes) | Preserves megabyte-scale files without DB bloat |
| Full Expected Outputs (System) | No | Yes (raw bytes) | Used by judge during submission grading |
| Custom Checker Binaries | No | Yes | Executable binary uploaded alongside tests |

---

## 8. Verification & Test Evidence

The following verification benchmarks were executed and confirmed on the live system:

1. **Problem Verified**:
   - **Polygon Problem ID**: `631622`
   - **Problem Title**: *Array Rotation*
   - **Database Problem ID**: `1`
2. **Test Case Inventory**:
   - 3 `SampleTestCase` records verified in PostgreSQL.
   - 10 `ProblemTestCase` records verified in PostgreSQL.
   - Total test cases: 13.
3. **Cloud Object Verification**:
   - Total files uploaded to Supabase private bucket `polygon-testcases`: **26 objects**.
   - Inputs: `test_cases/1/1` through `test_cases/1/13` (13 files).
   - Outputs: `test_cases/1/1.a` through `test_cases/1/13.a` (13 files).
   - Live existence check returned: `All 13 test cases (26 files) exist: True`.
4. **Byte-for-Byte Fidelity Check**:
   - Independent verification scripts downloaded every test input and output from Supabase Storage and compared them byte-for-byte against the PostgreSQL records.
   - All sample and non-truncated records matched with 100% byte fidelity.
5. **System Health**:
   - Django system check: `System check identified no issues (0 silenced)`.
   - Unit test suite: 9 problem ID normalization tests passed (`Ran 9 tests in 91.2s - OK`).
   - Optimization test suite: 2 mock optimization tests passed (`Ran 2 tests in 1.43s - OK`).
