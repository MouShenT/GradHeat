# GradHeat Java business service

Spring Boot 4.1.1, Java release 21, Maven 3.9.9. The build also works with the verified local JDK 23. The browser uses `/api/v1`; Python's internal routes are service-only. See `contracts/application-v1/README.md` for the shared message and HTTP contract.

## Build and check

```powershell
npm --prefix frontend ci
npm --prefix frontend run build
mvn -f backend/pom.xml clean verify
```

Build Vue first. Maven reads `frontend/dist` as a resource and embeds its production assets under the jar's `static/` directory; it does not copy generated files into `backend/src`. Vue uses HashRouter, so direct hash navigation needs no server catch-all. The Maven package/verify gate fails with an explicit `npm ci`/`npm run build` instruction if `frontend/dist/index.html` is missing. Use a clean build when distributing the jar to avoid carrying stale hashed assets in `target/classes`.

Tests create synthetic H2 tables. HTTP tests start two temporary servers on random local ports and close them after the test; they do not contact the VM, public platforms or the shared Chrome profile. No database migration runs automatically at application startup.

## Configuration

Copy the names from `.env.example` into your private launcher/environment. Spring does not automatically load that file. Keep secrets out of scripts and Git. Default bind is `127.0.0.1:18729`. The MySQL connection must point to the existing GradHeat database; Java only reads admissions publications/head and does not change Python's publish head. Apply the additive `crawler/sql/009_application_messaging.sql` once through the established checksum migration workflow before enabling tasks.

Redis is optional and reconstructable. Java reads the current head from MySQL, verifies the exact canonical UTF-8 bytes in `admissions_publication_bytes` against the existing publication SHA, and compares their parsed value with the MySQL JSON projection. Scientific notation and integer/decimal representation differences are compared by numeric meaning. A version-scoped Redis envelope must carry those same canonical bytes and satisfy `SHA256(body)==version`; corrupt or unavailable caches fall back to MySQL. The Python internal token is passed using `X-GradHeat-Internal-Token`; configure the same private `GRADHEAT_INTERNAL_TOKEN` on both services.

Writes are disabled by default. A configured `GRADHEAT_API_TOKEN` authorizes task creation/cancellation and immutable comparison saving through a Bearer header. A deliberately local installation may instead set `GRADHEAT_PUBLIC_WRITE_ENABLED=true`; keep the loopback bind and same-origin proxy. The current release has one local workspace, not a multi-user account/permission model. The Vite proxy should retain the browser Host (`changeOrigin: false`) so Origin checks stay effective. Do not expose this local service directly to the public internet.

```powershell
java -jar backend/target/gradheat-backend-0.1.0.jar
```

## Message delivery and recovery

Set `GRADHEAT_MESSAGING_ENABLED=true` only after configuring the private RabbitMQ vhost and verifying both sides. The service declares durable direct exchanges `gradheat.commands`, `gradheat.events` and `gradheat.deadletters`; work queues use `gradheat.<type>`, and the Java event queue is `gradheat.task.status`. Dead queues use `gradheat.dead.<type>` and identical routing keys.

Task creation and `app_outbox` insert share a JDBC transaction. `request_id` is a client-generated UUID: reusing it with the same type/version/scope returns the original task, while changed input returns 409. Outbox claims use a 30-second lease and `FOR UPDATE SKIP LOCKED`. Publishing is persistent, mandatory and requires a positive correlated confirm with no return. Failed/uncertain publishing leaves a retryable outbox record. Duplicate delivery remains possible and is expected.

Java consumes status events with manual ACK after the inbox/status transaction commits. Duplicate message IDs must retain identical content. Version, attempt and processor must match; lower/old sequence events and later events for stopped attempts are retained as stale without regressing state. A successful event also requires an already committed Python result, matching execution context, and an independently verified `result_bytes` SHA. Invalid messages go to the dead queue; a MySQL connectivity error NACKs with requeue. No payload or connection secret is logged.

`GET /api/v1/health` reports Java process liveness separately from verified publication readiness. It returns no database URL, host, credential or exception text. The Python bridge explicitly uses HTTP/1.1; automatic h2c upgrade was incompatible with the actual uvicorn integration and is now covered by a no-Upgrade-header regression assertion.

`GET /api/v1/tasks/{id}/result` returns only `analyse.long` results for the approved public analysis operations. Collection, extraction and information-verification task originals stay in the research database and are rejected by this public endpoint. Task status omits its private scope and paths.

Cancellation of an undispatched queued task cancels the pending outbox. For a dispatched/running task Java stores a cancellation request and waits for the worker's cooperative cancellation event; it does not claim the process has stopped. Old materials/results remain immutable.

Comparison calculation and report rendering are owned by Python. Java checks the supplied canonical archive and its SHA, stores exact canonical result bytes into the existing `personal_comparison.result_bytes`, and verifies them on read/export. Existing numeric representation is preserved; Java does not recompute floats or formulas.

For legacy comparison records with null `result_bytes`, only an independently verified Python backfill can guarantee scientific-notation compatibility. The Java fallback does not silently rewrite such records and returns an integrity error if reconstructed bytes do not match the original SHA.

## Current verification point

2026-10-10: collection controls, single-JSON preparation, bounded progress and operational downloads were added under `/api/v1/collection`. Authentication or deliberately enabled loopback access is required. The new task type is `collect.autonomous.win-primary`; raw input is frozen by Python and the command carries only its batch/SHA reference. The latest Maven verify passed 23 tests. Real analysis-chain acceptance passed 42 checks; the live Vue upload/collection/MySQL/download chain passed 16 checks. These are bounded checks, not proof of complete platform coverage. See `docs/APPLICATION-RUNBOOK.md`.

Initial `mvn verify` passed 19 tests. The follow-up `mvn -q -f backend/pom.xml test` passed **22 tests** (12 transaction/storage, 2 AMQP semantics, 8 temporary HTTP tests), including health, Vue entry serving and rejection of internal originals. `mvn -q -f backend/pom.xml package -DskipTests` then passed the frontend-build gate and produced a jar containing Vue's index/assets. The packaged application is `backend/target/gradheat-backend-0.1.0.jar`; `target/` is a local build output, not a Git artifact. Migration 009 is unchanged and frozen at SHA256 `1dff922cefbc25eb6a8772bb59f8c110b5b756331c31e4ceafd8131da5f81829`. These checks used synthetic data only. Root's migration/backfill and the module agent's real VM message round trips are recorded separately; this document does not independently certify their completion or persistent deployment.
