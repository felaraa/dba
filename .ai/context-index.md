# Context Index

Ultima revisao: 2026-06-25.

Este arquivo e o roteador de contexto para tarefas com IA no projeto
`oracle-query-otim`. Use-o para escolher o menor conjunto de arquivos antes de
editar codigo, testes ou documentacao. O objetivo e economizar tokens sem perder
seguranca tecnica.

## Como usar este indice

1. Identifique o dominio da tarefa.
2. Leia primeiro os arquivos em "Read first".
3. Leia "Then read" apenas se a tarefa exigir detalhe.
4. Rode os testes indicados em "Tests".
5. Evite arquivos listados em "Avoid unless needed".

Para qualquer mudanca significativa, atualize a memoria adequada em `.ai/`.
Mudancas triviais de formatacao, typo ou comentario sem impacto tecnico nao
devem gerar churn de memoria.

## Boot minimo de sessao

Use when task is broad, unclear, or starts a new agent session.

Read first:
- `AGENTS.md` for Codex workflow, memory rule, safety and token rules.
- `CLAUDE.md` for Claude Code boot context and current rule list.
- This file.

Then read:
- `README.md` for user-facing project overview and quickstart.
- `docs/ARQUITETURA.md` for the technical pipeline.
- `docs/CONTRIBUTING.md` for rule-plugin workflow.

Avoid unless needed:
- `plan.xml`, `plan2.xml`, `plan3.xml`.
- `examples/plan_*.xml`.
- `temp/`.

## Project Memory

Use when task changes project knowledge, documentation strategy, architecture,
implemented behavior, testing strategy, or repeated prompts.

Read first:
- `.ai/project-brief.md` for objective, scope, users and constraints.
- `AGENTS.md`
- `CLAUDE.md`
- `.ai/context-index.md`
- `.ai/implemented-index.md` when the task needs current implemented behavior,
  rule coverage, tests or known limitations.
- `.ai/decision-log.md` when the task touches durable architecture, product or
  operational decisions.
- `.ai/architecture-map.md` when the task touches module boundaries, data flow,
  folder structure or where logic should live.

Memory files in this structure:
- `.ai/project-brief.md` for objective, scope, users and constraints.
- `.ai/context-index.md` for context routing by task/domain.
- `.ai/implemented-index.md` for implemented behavior, files, tests and known
  limitations.
- `.ai/decision-log.md` for architectural/product/operational decisions.
- `.ai/architecture-map.md` for module map and data flow.
- `.ai/coding-rules.md` for coding and DDL conventions.
- `.ai/testing-rules.md` for test matrix and commands.
- `.ai/prompt-recipes.md` for reusable prompts.

Update rules:
- Update `.ai/implemented-index.md` when behavior, rules, important files,
  commands or tests change.
- Update `.ai/decision-log.md` when a durable architectural, product or
  operational decision is made.
- Update `.ai/context-index.md` when a new domain, module, flow, document or
  important file group appears.
- Update `.ai/architecture-map.md`, `.ai/coding-rules.md` or
  `.ai/testing-rules.md` when the change affects architecture, coding standards
  or testing strategy.

Tests:
- Documentation-only memory changes usually do not need test execution.
- If memory describes code behavior, verify the referenced tests still exist.

## Core Architecture

Use when task involves pipeline boundaries, contracts, module responsibilities,
or "where should this logic live?".

Read first:
- `src/advisor/models.py`
- `src/advisor/rule_base.py`
- `src/advisor/engine.py`
- `docs/ARQUITETURA.md`

Then read:
- `.ai/architecture-map.md`
- `src/advisor/reporter.py`
- `src/advisor/cli.py`
- `README.md`

Key facts:
- `models.py` defines shared dataclasses: `ParsedQuery`, `ParsedPlan`,
  `SchemaMetadata`, `PlanHistory`, `Recommendation`.
- `RuleContext` is immutable and is the only input rules should inspect.
- `RuleEngine` discovers rule plugins automatically from `src/advisor/rules/`.
- `engine.py` must remain generic; tuning logic belongs in rules.
- `reporter.py` handles presentation, index consolidation and mitigation merge.

Tests:
- `python -m pytest -q tests/test_pipeline.py`
- `python -m pytest -q` if a shared contract changed.

Avoid unless needed:
- Individual XML plan fixtures; prefer tests and parser code first.

## New Or Changed Tuning Rule

Use when task says add, modify, disable, rank, explain, or test a detection or
recommendation rule.

Read first:
- `.claude/skills/criar-regra/SKILL.md` if using Claude Code or following the
  local rule creation ritual.
- `src/advisor/rule_base.py`
- `src/advisor/rules/__init__.py`
- One similar rule in `src/advisor/rules/rule_*.py`.
- The closest test in `tests/test_*.py`.

Then read:
- `src/advisor/models.py` for available context fields.
- `docs/CONTRIBUTING.md`
- `CLAUDE.md` rule list.
- Relevant fixture in `tests/fixtures_*.py`.
- Relevant SQL/plan in `examples/`.

Current rule map:
- `R001_filter_should_be_access`: `rule_filter_should_be_access.py`,
  `tests/test_pipeline.py`.
- `R002_avoidable_full_scan`: `rule_full_scan.py`, covered by pipeline and
  related index tests.
- `R003_covering_for_aggregation`: `rule_covering_aggregation.py`,
  `tests/test_pipeline.py`.
- `R004_cartesian_or_bad_estimates`: `rule_cartesian_and_bad_estimates.py`,
  `tests/test_cartesian_case.py`, `tests/test_improvements_v3.py`.
- `R005_existing_intervention`: `rule_existing_intervention.py`,
  `tests/test_cartesian_case.py`.
- `R006_buffer_sort_materialization`: `rule_buffer_sort_materialization.py`,
  pipeline/aggregation cases.
- `R007_unused_existing_index`: `rule_unused_existing_index.py`,
  `tests/test_unused_index_case.py`.
- `R008_global_index_on_partitioned`: `rule_global_index_on_partitioned.py`,
  `tests/test_global_index_rule.py`, `sql/audit_global_indexes_on_partitioned.sql`.
- `R009_plan_instability`: `rule_plan_instability.py`,
  `tests/test_plan_instability.py`, `tests/fixtures_plan_instability.py`.
- `R010_workarea_spill_to_temp`: `rule_workarea_spill.py`,
  `tests/test_workarea_spill.py`.
- `R011_massive_rowid_access`: `rule_massive_rowid_access.py`,
  `tests/test_massive_rowid_access.py`, `tests/test_owner_resolution.py`.
- `R900_rac_hotblock_mitigation`: `rule_rac_hotblock_mitigation.py`,
  `tests/test_pipeline.py`.

Index-rule conventions:
- Resolve owner with `ctx.resolve_owner()`.
- Decide locality with `ctx.is_partitioned(owner, table)`.
- Generate names with `build_index_name(..., owner=owner)`.
- Generate DDL with `build_index_ddl(..., parallel=ctx.env.index_parallel,
  tablespace=ctx.env.index_tablespace)`.
- Check existing indexes with `existing_index_covering` or
  `existing_index_exact_or_superset`.
- Do not manually consolidate duplicate recommendations; use reporter flow.

Tests:
- New rule: add a focused `tests/test_<domain>.py` and fixture if needed.
- Rule isolated: `python -m pytest -q tests/test_<domain>.py`.
- Shared helpers or contracts: `python -m pytest -q`.

Memory:
- Update `.ai/implemented-index.md` for new/changed rule behavior and tests.
- Update `.ai/decision-log.md` if priority ranges or rule design changed.
- Update this file if a new rule domain needs its own routing section.

Avoid unless needed:
- Editing `engine.py` to register a rule.
- Reading every rule; choose the closest one.

## SQL Parser

Use when task involves parsing SQL text, aliases, owners, joins, predicates,
projection, group by, Oracle binds, or `sqlglot` behavior.

Read first:
- `src/advisor/sql_parser.py`
- `src/advisor/models.py` (`ParsedQuery`, `TableRef`, `ColumnRef`,
  `JoinPredicate`, `FilterPredicate`)
- `tests/test_pipeline.py`

Then read:
- SQL examples in `examples/query*.sql`.
- Fixtures only if parser output feeds rule assertions.

Key facts:
- Oracle binds `:1` are normalized to `:b1` before `sqlglot`.
- Only qualified columns with known aliases become `ColumnRef`.
- Joins are equality predicates between columns from different table aliases.
- Range filters are grouped by column.
- Projection/group-by extraction scans all `SELECT` nodes.

Tests:
- `python -m pytest -q tests/test_pipeline.py`
- Add focused parser assertions near existing SQL parser tests when possible.

Avoid unless needed:
- Plan parser files; SQL parser changes often do not require plan context.

## Plan Parser

Use when task involves SQL Monitor XML, DBMS_XPLAN text, operation hierarchy,
runtime stats, predicates, A-Rows/E-Rows, SQL Profile/Baseline notes,
workarea/temp/spill metrics, or owner extraction from plans.

Read first:
- `src/advisor/plan_parser.py`
- `src/advisor/models.py` (`ParsedPlan`, `PlanOperation`)
- `tests/test_pipeline.py`
- `tests/test_cartesian_case.py`

Then read:
- `tests/test_workarea_spill.py` for XML workarea metrics.
- `tests/test_owner_resolution.py` for object owner extraction.
- Relevant small `examples/plan*.txt`; XML only when needed.

Key facts:
- `parse_plan` auto-detects XML vs DBMS_XPLAN text.
- SQL Monitor XML combines static `<plan>` and runtime `<plan_monitor>`.
- Runtime XML can provide `object_owner`, `temp_bytes`, `spill_count`,
  `write_bytes`.
- Text parser reconstructs hierarchy by indentation and attaches predicate
  information by operation id.

Tests:
- `python -m pytest -q tests/test_pipeline.py tests/test_cartesian_case.py`
- `python -m pytest -q tests/test_workarea_spill.py tests/test_owner_resolution.py`
- Full suite if `PlanOperation` fields change.

Avoid unless needed:
- Large root-level `plan*.xml`; prefer targeted example XML fixtures.

## Metadata Collection

Use when task involves Oracle dictionary views, table/index/column metadata,
partitioning, stale stats, views, missing tables, existing indexes, index usage,
or fixture metadata.

Read first:
- `src/advisor/metadata_collector.py`
- `src/advisor/models.py` (`SchemaMetadata`, `TableMeta`, `ColumnStats`,
  `IndexMeta`)
- `tests/test_index_collection_fixes.py`
- `tests/test_improvements_v3.py`

Then read:
- `docs/GUIA_DE_COLETA.md`
- Relevant `tests/fixtures_*.py`
- `config/db.yaml.example` for connection shape only; never real credentials.

Key facts:
- `OracleMetadataCollector` reads `DBA_TABLES`, `DBA_VIEWS`,
  `DBA_PART_TABLES`, `DBA_TAB_COL_STATISTICS`, `DBA_INDEXES`,
  `DBA_IND_COLUMNS`, `DBA_INDEX_USAGE`, and stats health views.
- Collection is resilient: missing/failed table metadata should not kill the
  pipeline.
- Index rows are materialized with `fetchall()` before nested cursor queries;
  this fixed a real silent-loss bug.
- Existing index matching for equality leaders compares sets, not only order.

Tests:
- `python -m pytest -q tests/test_index_collection_fixes.py`
- `python -m pytest -q tests/test_improvements_v3.py`
- Add integration tests only behind `@pytest.mark.integration` and `ORACLE_*`.

Avoid unless needed:
- Connecting to a real database without explicit user request/approval.
- Hardcoding owner-specific exceptions in rules.

## Env Profile And AWR

Use when task involves `env_profile_*.yaml`, RAWDB/DATADB calibration, AWR HTML,
hot segments, CPU-bound thresholds, scoring, DDL options, RAC contention, or
profile create/update behavior.

Read first:
- `src/advisor/env_profile.py`
- `src/advisor/awr_parser.py`
- `src/advisor/profile_builder.py`
- `src/advisor/awr_cli.py`
- `docs/GUIA_ENV_PROFILE.md`
- `tests/test_awr_profile.py`

Then read:
- `config/env_profile_rawdb.yaml`
- `config/env_profile_datadb.yaml`
- `tests/fixtures/env_profile_rawdb.yaml` when test expectations need stable
  regression data.
- `tests/fixtures/awr_sample.html` only if parser fixture details matter.

Key facts:
- Environment is data, not code.
- `advisor.awr_cli` creates/updates commented YAML from one or more AWR HTMLs.
- `--update` preserves human fields such as `scoring.*`, `index_ddl.*`,
  `identity.exadata`, `io.full_scan_block_discount`, and
  `workload.benefit_metric`.
- AWR parsing is resilient and reports missing metrics.
- RAC aggregation averages numeric load metrics and unions hot segments.

Tests:
- `python -m pytest -q tests/test_awr_profile.py`
- Use temp output under `temp/` or pytest `tmp_path`, not committed files.

Memory:
- Update `.ai/implemented-index.md` when profile behavior or fields change.
- Update `.ai/decision-log.md` for new threshold or preservation decisions.

Avoid unless needed:
- Editing generated env profiles without understanding human vs AWR-derived
  fields.

## Plan History And Instability

Use when task involves SQL_ID plan history, `GV$SQL`, `DBA_HIST_SQLSTAT`,
`PlanHistory`, best/worst plans, or R009.

Read first:
- `src/advisor/plan_history.py`
- `src/advisor/models.py` (`PlanHistory`, `PlanStat`)
- `src/advisor/rules/rule_plan_instability.py`
- `tests/test_plan_instability.py`
- `tests/fixtures_plan_instability.py`

Then read:
- `src/advisor/cli.py` where history is collected in DB mode.
- `src/advisor/batch.py` where history is collected for each SQL_ID.

Key facts:
- History is collected only in DB-backed flows; fixture mode uses empty
  `PlanHistory` unless a test builds one explicitly.
- Sources are merged by `plan_hash_value`.
- Metrics are averaged per execution.
- Failures against AWR views must be defensive; Diagnostics Pack may be
  unavailable.

Tests:
- `python -m pytest -q tests/test_plan_instability.py`

Avoid unless needed:
- Making R009 depend on current plan file only; its purpose is historical
  instability.

## CLI Single Query And SQL_ID Flow

Use when task involves `advisor`, CLI flags, argument validation, `--sql`,
`--plan`, `--sql-id`, `--source`, `--fixture`, `--diag`, `--format`,
`--validate`, temp artifact saving, or orchestration of parser/collector/engine.

Read first:
- `src/advisor/cli.py`
- `src/advisor/db_connection.py`
- `src/advisor/reporter.py`
- `README.md`
- `docs/MANUAL_DE_USO.md`

Then read:
- `src/advisor/batch.py` for shared SQL_ID fetch helpers.
- `src/advisor/validator.py` if `--validate` is involved.
- `tests/test_pipeline.py` for offline fixture flow.

Key facts:
- Input modes are mutually exclusive: files (`--sql` + `--plan`) or `--sql-id`.
- `--sql-id` requires DB source, fetches SQL text and plan from the database,
  and can save artifacts under `temp/<sql_id>/`.
- `source=fixture` imports a fixture module with `get_metadata()`.
- DB mode resolves credentials through CLI args, environment, YAML, or wallet.
- `--validate` is opt-in and ignored for fixture.

Tests:
- `python -m pytest -q tests/test_pipeline.py`
- CLI behavior currently has limited direct test coverage; add focused tests if
  changing argument validation or outputs.

Avoid unless needed:
- Real DB commands or `--validate` without explicit user intent.
- Logging passwords or embedding credentials in docs/tests.

## Batch Analysis

Use when task involves `advisor-batch`, top SQL selection, batch report,
GV$SQL/GV$SQLTEXT, SQL Monitor fallback, consolidated DDL across SQL_IDs, or
saved temp SQL/plan artifacts.

Read first:
- `src/advisor/batch.py`
- `src/advisor/batch_cli.py`
- `src/advisor/cli.py` for shared single-query flow concepts.
- `src/advisor/reporter.py`

Then read:
- `sql/top_sql_awr.sql` if task involves AWR/top SQL scripts.
- `docs/MANUAL_DE_USO.md` if user-facing instructions change.

Key facts:
- Batch mode requires DB source; fixture is not supported.
- Default top SQL filter is last hour with average elapsed > 10 minutes,
  ordered by buffer gets.
- For each SQL_ID, SQL and plan are saved under `temp/<sql_id>/`.
- Each query result can be skipped, errored, or have recommendations.

Tests:
- Existing unit coverage is sparse for batch. Add focused tests around pure
  formatting or helper behavior if changing it.
- Run `python -m pytest -q` after shared reporter/model changes.

Avoid unless needed:
- Changing top SQL thresholds without recording a decision.

## Reporting And Output Formatting

Use when task involves final text/Markdown output, sorting by severity/score,
index consolidation, mitigation warning merge, DDL display, or report wording.

Read first:
- `src/advisor/reporter.py`
- `src/advisor/models.py` (`Recommendation`, `Severity`)
- `tests/test_pipeline.py`
- `tests/test_unused_index_case.py`

Then read:
- `src/advisor/batch_cli.py` for batch-specific formatting.
- `examples/resultado_*.md` for user-facing examples.

Key facts:
- `consolidate_indexes` removes redundant index recommendations by table and
  column-prefix relationship.
- `merge_mitigation_warnings` attaches warning-only mitigation recs to index
  recs on the same target table.
- Final output sorts by severity first, then score.

Tests:
- `python -m pytest -q tests/test_pipeline.py tests/test_unused_index_case.py`
- Add output tests if changing report structure.

Avoid unless needed:
- Coupling presentation rules back into `engine.py`.

## Validation With Invisible Indexes

Use when task involves `--validate`, temporary index creation, invisible
indexes, measuring buffer gets, optimizer invisible index session setting, or
cleanup behavior.

Read first:
- `src/advisor/validator.py`
- `src/advisor/cli.py` (`_run_validation`)
- `docs/MANUAL_DE_USO.md`

Then read:
- `src/advisor/rules/__init__.py` for DDL shape.
- `config/db.yaml.example` for credential patterns.

Key facts:
- Validation creates an index as `INVISIBLE`, enables
  `optimizer_use_invisible_indexes` only for the session, measures query stats,
  then attempts to drop the test index.
- It consumes real database resources and can generate redo.
- It should never run accidentally for fixture mode.

Tests:
- Unit coverage is limited because this is DB-side behavior.
- Integration tests must be explicit, marked, and skipped without `ORACLE_*`.

Avoid unless needed:
- Running validation against production without explicit operator approval.

## DB Connection And Credentials

Use when task involves connection resolution, Oracle thin/thick mode, wallet,
`config/db.yaml.example`, environment variables, or credential safety.

Read first:
- `src/advisor/db_connection.py`
- `config/db.yaml.example`
- `docs/MANUAL_DE_USO.md`

Then read:
- `src/advisor/cli.py`
- `src/advisor/batch_cli.py`

Key facts:
- Priority: CLI args > `ORACLE_*` environment variables > YAML config >
  wallet/TNS.
- `config/db.yaml` should not be committed.
- `oracledb` is optional and required only for DB-backed flows.
- Thin mode is default; thick mode requires client library path.

Tests:
- Add pure unit tests for config resolution if behavior changes.
- Do not require a real Oracle DB in normal unit tests.

Avoid unless needed:
- Printing secrets in command examples, test output, or docs.

## Tests And Fixtures

Use when task involves adding regression coverage, choosing where to test,
fixture metadata, examples, or test strategy.

Read first:
- `pyproject.toml`
- `tests/test_pipeline.py`
- Closest `tests/test_*.py` by domain.
- Closest `tests/fixtures_*.py`.

Then read:
- `docs/CONTRIBUTING.md`
- `examples/query*.sql`
- Relevant `examples/plan*.txt` or `examples/plan_*.xml`.

Important tests by domain:
- Pipeline/parser/rules baseline: `tests/test_pipeline.py`.
- Cartesian/profile/intervention: `tests/test_cartesian_case.py`.
- Stale stats/local inference/index naming/DDL stats: `tests/test_improvements_v3.py`.
- Existing index collection/matching: `tests/test_index_collection_fixes.py`.
- Unused existing index: `tests/test_unused_index_case.py`.
- Plan instability: `tests/test_plan_instability.py`.
- Workarea spill: `tests/test_workarea_spill.py`.
- Massive rowid access: `tests/test_massive_rowid_access.py`.
- Owner resolution: `tests/test_owner_resolution.py`.
- DDL options: `tests/test_index_ddl_options.py`.
- Global index on partitioned table: `tests/test_global_index_rule.py`.
- AWR/profile generation: `tests/test_awr_profile.py`.

Commands:
- `python -m pytest -q`
- `python -m pytest -q tests/test_pipeline.py`
- `python -m pytest -q tests/test_awr_profile.py`

Memory:
- Update `.ai/testing-rules.md` when strategy or commands change.
- Update `.ai/implemented-index.md` when new regression cases are added.

Avoid unless needed:
- Making tests depend on a live Oracle DB unless marked integration and skipped
  without credentials.

## Examples And Input Artifacts

Use when task involves sample SQL, sample plans, generated reports, or adding a
new real-case regression artifact.

Read first:
- `examples/query*.sql`
- Closest `examples/plan*.txt` or `examples/plan_*.xml`
- Closest `examples/resultado_*.md` if report output matters.
- Matching `tests/fixtures_*.py`

Current notable examples:
- `examples/query.sql` + `examples/plan.txt`: baseline 24h537gmxw93d pipeline.
- `examples/query_cartesian.sql` + `examples/plan_cartesian.xml`.
- `examples/query_unused_idx.sql` + `examples/plan_unused_idx.xml`.
- `examples/query_stale_stats.sql` + `examples/plan_stale_stats.xml`.
- `examples/query_plan_instability.sql` + `examples/plan_instability.xml`.
- `examples/query_agg_merge_spill.sql` + `examples/plan_agg_merge_spill.xml`.
- `examples/query_agg_merge_adjn.sql` + `examples/plan_agg_merge_adjn.xml`.

Tests:
- Add or update the matching `tests/test_*.py`.

Avoid unless needed:
- Reading all XML examples. Pick the example tied to the failing or new test.

## Documentation

Use when task involves user docs, collection guide, architecture docs,
contributing workflow, tuning plan, or README.

Read first:
- `README.md`
- `docs/MANUAL_DE_USO.md`
- `docs/ARQUITETURA.md`
- `docs/CONTRIBUTING.md`

Then read by topic:
- Project scope/business context: `.ai/project-brief.md`.
- Data collection: `docs/GUIA_DE_COLETA.md`.
- Env profile/AWR: `docs/GUIA_ENV_PROFILE.md`.
- RAWDB operational tuning: `docs/plano_tuning_rawdb.md`.
- Agent boot docs: `AGENTS.md`, `CLAUDE.md`.
- AI memory/inventory: `.ai/context-index.md`, `.ai/implemented-index.md`,
  `.ai/decision-log.md`, `.ai/prompt-recipes.md`, `.ai/architecture-map.md`.

Memory:
- Update `.ai/implemented-index.md` if docs describe implemented behavior.
- Update `.ai/decision-log.md` if docs record a durable decision.
- Update this file if new doc groups are added.

Tests:
- Documentation-only changes usually do not need tests.
- Run focused tests when docs examples depend on changed commands.

Avoid unless needed:
- Duplicating long docs into agent boot files; prefer links and routing.

## SQL Support Scripts

Use when task involves DBA helper SQL, global index audits, top SQL extraction,
manual collection scripts, or database-side diagnostics outside Python.

Read first:
- `sql/audit_global_indexes_on_partitioned.sql`
- `sql/top_sql_awr.sql`
- `docs/GUIA_DE_COLETA.md`

Then read:
- `src/advisor/rules/rule_global_index_on_partitioned.py`
- `src/advisor/batch.py`

Tests:
- If a Python rule consumes the same concept, update matching Python tests.
- SQL scripts usually need manual review unless a parser/test harness exists.

Avoid unless needed:
- Assuming SQL script output shape is enforced by tests; document assumptions.

## Packaging And Dependencies

Use when task involves installation, console scripts, Python version,
dependencies, pytest config, optional extras, or bootstrap.

Read first:
- `pyproject.toml`
- `requirements.txt`
- `scripts/bootstrap.sh`
- `README.md`

Then read:
- CLI modules referenced by `[project.scripts]`.

Key facts:
- Requires Python >= 3.10.
- Core deps: `sqlglot`, `PyYAML`.
- Optional `db`: `oracledb`.
- Optional `dev`: `pytest`.
- Console scripts: `advisor`, `advisor-awr`, `advisor-batch`.

Tests:
- `python -m pytest -q` after dependency or packaging changes.

Memory:
- Update `.ai/decision-log.md` for new dependency decisions.
- Update `.ai/implemented-index.md` if scripts or install flow change.

Avoid unless needed:
- Adding dependencies for simple parsing/formatting already covered by stdlib or
  existing libs.

## Quick Task Lookup

Use this quick map when the task wording is short:

- "adicione uma regra": New Or Changed Tuning Rule.
- "erro no DDL de indice": New Or Changed Tuning Rule, Reporting, Env Profile
  if `parallel` or `tablespace` is involved.
- "owner None" or "schema errado": New Or Changed Tuning Rule, Plan Parser,
  Metadata Collection, tests `test_owner_resolution.py`.
- "plano XML nao parseia": Plan Parser.
- "A-Rows/E-Rows errado": Plan Parser, then affected rule.
- "SQL nao extrai join/filtro": SQL Parser.
- "indice existente duplicado": Metadata Collection, New Or Changed Tuning Rule,
  tests `test_index_collection_fixes.py`.
- "estatistica obsoleta": Metadata Collection, R004, collection guide.
- "SQL_ID": CLI Single Query And SQL_ID Flow, Plan History if multiple plans.
- "top queries" or "batch": Batch Analysis.
- "AWR" or "env_profile": Env Profile And AWR.
- "relatorio markdown/texto": Reporting And Output Formatting.
- "validar indice": Validation With Invisible Indexes.
- "credenciais/wallet/thick": DB Connection And Credentials.
- "teste/fixture": Tests And Fixtures.
- "README/docs": Documentation.
- "prompt para IA": Documentation, Project Memory, `.ai/prompt-recipes.md`.
- "objetivo/escopo/usuarios": Project Memory, `.ai/project-brief.md`.

## Global Avoid List

Avoid reading or changing these unless directly relevant:

- `plan.xml`, `plan2.xml`, `plan3.xml`: large root artifacts.
- `examples/plan_*.xml`: read only the one tied to the target test/case.
- `temp/`: generated artifacts from SQL_ID/batch flows.
- `.venv/`, `.pytest_cache/`, `.git/`.
- Real credential files such as `config/db.yaml` if present.

Never commit secrets. Prefer examples using `config/db.yaml.example` or
`ORACLE_*` environment variables.
