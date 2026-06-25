# Decision Log

Ultima revisao: 2026-06-25.

Este arquivo registra decisoes duraveis do projeto. Ele nao substitui
documentacao detalhada nem historico Git; serve para impedir que agentes reabram
decisoes ja tomadas sem necessidade. Novas entradas devem ser curtas, com
Decision, Reason e Implications.

## 2026-06-25 — Keep AI memory in `.ai/`

Decision:
Project memory for AI agents should live under `.ai/`, with `context-index.md`
as the router and `implemented-index.md` as the inventory of current behavior.

Reason:
Agent boot files (`AGENTS.md` and `CLAUDE.md`) must stay small enough for every
session, while deeper project knowledge should be loaded only when relevant.

Implications:
- Update `.ai/implemented-index.md` when behavior, rules, commands, files or
  tests change.
- Update `.ai/context-index.md` when a new domain, module, flow or important
  file group appears.
- Future memory files should include project brief, architecture map, coding
  rules, testing rules and prompt recipes.
- Do not update memory for formatting-only or typo-only changes.

## 2026-06-25 — Use separate boot files for Codex and Claude Code

Decision:
Maintain both `AGENTS.md` and `CLAUDE.md`, with overlapping facts but different
operational emphasis.

Reason:
Codex and Claude Code load and use project context differently. A single generic
file either becomes too long or fails to encode tool/workflow-specific guidance.

Implications:
- Keep `AGENTS.md` focused on Codex operational workflow, safe editing, context
  routing and token economy.
- Keep `CLAUDE.md` focused on Claude Code boot context, rule creation workflow
  and the local `.claude/skills/criar-regra/` skill.
- Durable project facts should eventually move into `.ai/` files and be linked
  from both boot files.

## 2026-06-25 — Engine remains generic; tuning logic lives in rules

Decision:
`src/advisor/engine.py` must stay a deterministic plugin runner. New tuning
behavior belongs in `src/advisor/rules/` as a `Rule` implementation.

Reason:
This preserves the central design: rules are independently addable/removable,
can fail without breaking the whole pipeline, and are easy to regression-test
against real cases.

Implications:
- Do not edit `engine.py` to register a new rule.
- New rules must subclass `Rule`, read only `RuleContext`, and return
  `Recommendation` objects.
- Use `--allow` and `--deny` for runtime rule selection.
- Add or update tests for every new rule or behavior change.

## 2026-06-25 — Rules are deterministic and AI is explanatory only

Decision:
Rules must be deterministic and auditable. AI may be used later as an
explanation layer, but not as the source of tuning truth.

Reason:
The output is used for DBA decisions in Oracle/RAC environments. Recommendations
must be reproducible, testable and explainable from SQL, plan, metadata and
environment profile.

Implications:
- Do not call LLMs from rules.
- Keep heuristics visible in code and covered by tests/fixtures.
- If an `--explain` feature is added later, it should summarize rule output, not
  override it.

## 2026-06-25 — `RuleContext` is immutable and rules do not communicate

Decision:
Rules receive an immutable `RuleContext` and do not inspect or mutate
recommendations produced by other rules.

Reason:
Isolation keeps rule ordering predictable and prevents hidden dependencies
between diagnoses.

Implications:
- Cross-rule presentation behavior belongs in `reporter.py`.
- Mitigation rules, such as R900, emit independent warnings that are merged by
  `merge_mitigation_warnings`.
- If future behavior needs shared facts, add them to `RuleContext` explicitly
  rather than reading another rule's output.

## 2026-06-25 — Environment calibration is data, not code

Decision:
Environment-specific calibration belongs in `config/env_profile_*.yaml`, loaded
through `env_profile.py`, not hardcoded in rules.

Reason:
The same advisor must work across RAWDB, DATADB and future Oracle environments
with different workload, RAC contention, DDL options and scoring.

Implications:
- Recalibrate by editing or regenerating an env profile, not by adding
  owner/database exceptions to rules.
- Rules should use `ctx.env` for scoring, hot segments, CPU-bound assumptions and
  DDL options.
- Changing `scoring.*` or `index_ddl.*` can change recommendations and should be
  treated as behavior-affecting.

## 2026-06-25 — AWR parser reads facts; profile builder applies policy

Decision:
`awr_parser.py` only extracts raw AWR facts. `profile_builder.py` applies
thresholds, defaults and preservation rules to produce `env_profile_*.yaml`.

Reason:
Separating parsing from calibration keeps AWR format handling independent from
advisor policy and makes update behavior testable.

Implications:
- Add new AWR extraction in `awr_parser.py`.
- Add new derived/profile behavior in `profile_builder.py`.
- Keep AWR parsing resilient; missing sections should report diagnostics rather
  than crash.
- Add or update `tests/test_awr_profile.py` for parser/builder changes.

## 2026-06-25 — `advisor.awr_cli --update` preserves human fields

Decision:
Updating an env profile from a new AWR refreshes AWR-derived fields and
preserves human-calibrated fields.

Reason:
Fields such as scoring weights, DDL options and Exadata classification are
operator decisions, not facts reliably derived from AWR.

Implications:
- Preserve `scoring.*`, `index_ddl.*`, `identity.exadata`,
  `io.full_scan_block_discount` and `workload.benefit_metric` on update.
- Re-emit the YAML using the commented template.
- If a new field is added, decide explicitly whether it is AWR-derived or human.

## 2026-06-25 — Index DDL must be owner-qualified and collect index stats

Decision:
All generated index DDL must create the index in the table owner schema and run
`DBMS_STATS.GATHER_INDEX_STATS` afterward.

Reason:
Real cases showed owner may be absent from SQL text. Creating an index under the
connected user or without statistics can make the recommendation wrong or unused
by the optimizer.

Implications:
- Use `ctx.resolve_owner()` before DDL generation.
- Use `build_index_ddl()` for index recommendations.
- DDL should include `CREATE INDEX owner.idx ON owner.table ...` and index stats
  collection.
- Tests around owner resolution and DDL options must stay green.

## 2026-06-25 — Partitioned tables default to `LOCAL` indexes

Decision:
Generated indexes for partitioned tables should be `LOCAL`.

Reason:
Local indexes align with partition maintenance and avoid accidental global index
maintenance debt. Metadata can be incomplete, so the advisor also infers
partitioning from plan operations.

Implications:
- Use `ctx.is_partitioned(owner, table)` rather than assuming non-partitioned
  when metadata is missing.
- Rules should not generate global indexes for partitioned tables by default.
- R008 exists to warn about existing global indexes on partitioned tables.

## 2026-06-25 — Existing index matching for equality leaders is set-based

Decision:
For equality join leaders, `existing_index_covering` treats the first N index
columns as a set, not a strict ordered sequence.

Reason:
For equality probes, the order among equality columns often does not change
utility. A real case produced a redundant recommendation that only reordered
existing equality columns.

Implications:
- Do not recommend a new index only because equality leader order differs.
- Use `existing_index_covering` for probe-style index checks.
- Use `existing_index_exact_or_superset` only when ordered prefix semantics are
  required.

## 2026-06-25 — Reporter owns consolidation and mitigation merge

Decision:
Rules emit recommendations independently. `reporter.py` performs index
consolidation and merges mitigation warnings.

Reason:
This keeps `engine.py` and rules focused on detection, while presentation-level
deduplication stays in one place.

Implications:
- Do not manually deduplicate overlapping index recommendations inside rules.
- Keep `consolidate_indexes` and `merge_mitigation_warnings` covered when
  changing output behavior.
- Be careful changing DDL text shape because consolidation extracts columns via
  regex.

## 2026-06-25 — Validation is explicit and uses invisible indexes

Decision:
Real measurement of recommendations is opt-in via `--validate` and uses
temporary invisible indexes in the current session.

Reason:
Index creation consumes resources and generates redo. Invisible indexes reduce
plan risk for other sessions while allowing measured validation.

Implications:
- Never run validation implicitly.
- Fixture mode must not execute validation.
- Validation can be suggested, but running it against production requires clear
  operator intent.
- Keep cleanup logic defensive; temporary indexes must be dropped even on error.

## 2026-06-25 — Real DB tests must be integration-gated

Decision:
Normal unit tests should not require Oracle. Tests needing a live database must
be marked `integration` and skipped unless the required `ORACLE_*` environment
variables are available.

Reason:
The project must remain testable offline with fixtures, and CI/local agent runs
should not depend on production access or credentials.

Implications:
- Prefer fixtures for parser, rule and reporter regression.
- Protect live DB tests with `@pytest.mark.integration` and `skipif`.
- Do not put credentials in tests, docs or command output.

## 2026-06-25 — Plan history is collected only in DB-backed flows

Decision:
`PlanHistory` is populated from `GV$SQL` and `DBA_HIST_SQLSTAT` in DB-backed
flows; fixture mode defaults to an empty history unless a test injects one.

Reason:
Plan instability requires live or historical database observations, not just a
single plan file.

Implications:
- R009 must stay inert when history has fewer than two distinct plans.
- CLI and batch flows should collect plan history when connected to a database.
- Failures reading AWR views must be defensive because privileges/licensing may
  vary.

## 2026-06-25 — Batch mode requires a database source

Decision:
`advisor-batch` does not support fixture mode.

Reason:
Batch analysis selects live top SQL_IDs from Oracle dynamic performance views and
fetches SQL text/plans from the database.

Implications:
- Keep fixture support in single-query flow.
- Batch CLI should reject `--source fixture`.
- Changes to batch top SQL thresholds or selection criteria should be recorded
  as decisions.

## 2026-06-25 — Metadata collection must be resilient per table

Decision:
Metadata collection should continue when one table/view/stat query fails and
report missing tables instead of aborting the whole analysis.

Reason:
Real database permissions, views and object ownership can be inconsistent. A
partial analysis with diagnostics is more useful than a hard failure.

Implications:
- Preserve `collector.missing` behavior.
- Rules should handle incomplete metadata defensively.
- Use plan-based fallbacks such as `ctx.is_partitioned` and `ctx.resolve_owner`
  when metadata is incomplete.

## 2026-06-25 — Materialize index metadata rows before nested cursor queries

Decision:
`OracleMetadataCollector._indexes` must fetch all index rows before calling
helper queries for columns and usage on the same cursor.

Reason:
A real bug reused the cursor inside the iteration and silently discarded most
index rows, causing duplicate or missing index reasoning.

Implications:
- Keep the `fetchall()` pattern before nested `_index_cols` and `_index_usage`
  calls.
- Maintain `tests/test_index_collection_fixes.py`.

## 2026-06-25 — SQL Monitor XML is preferred over DBMS_XPLAN text

Decision:
When available, SQL Monitor XML should be the preferred plan input.

Reason:
XML carries explicit runtime hierarchy, SQL Profile notes, object owner and
workarea/TEMP metrics that DBMS_XPLAN text may not include.

Implications:
- `parse_plan` should continue auto-detecting XML vs text.
- Workarea-spill features depend on XML metrics.
- DBMS_XPLAN remains supported as fallback, especially when SQL Monitor is not
  available.

## 2026-06-25 — Credentials stay outside the repository

Decision:
Real credentials, wallets and `config/db.yaml` should not be committed or shown
in examples.

Reason:
The tool can connect to production Oracle databases. Credential leakage would be
high impact.

Implications:
- Use `config/db.yaml.example` for structure.
- Prefer `ORACLE_*` environment variables or wallet in docs/examples.
- Do not echo passwords in commands, tests or logs.

## 2026-06-25 — Case regressions live in tests and fixtures

Decision:
Every meaningful real-world tuning case should become a regression test with
query/plan artifacts and fixture metadata as needed.

Reason:
The advisor encodes DBA heuristics; real cases prevent regressions in parser,
metadata and rule behavior.

Implications:
- Add examples under `examples/`.
- Add `tests/fixtures_<case>.py` when metadata is needed.
- Add focused asserts in `tests/test_<domain>.py`.
- Update `.ai/implemented-index.md` when a new case is added.
