-- =============================================================================
-- top_sql_awr.sql
-- Top SQLs dos últimos 4 snapshots do AWR, agregando as instâncias RAC.
-- Foco: identificar candidatos a investigação no advisor.
-- Requer Diagnostics Pack. Sem licença, use o bloco gv$sql ao final.
-- =============================================================================

WITH snaps AS (
  SELECT snap_id, dbid, instance_number
  FROM   dba_hist_snapshot
  WHERE  snap_id > (SELECT MAX(snap_id) - 4 FROM dba_hist_snapshot)
),
sqlstat AS (
  SELECT s.sql_id,
         SUM(s.elapsed_time_delta)/1e6   elapsed_s,
         SUM(s.cpu_time_delta)/1e6       cpu_s,
         SUM(s.buffer_gets_delta)        buffer_gets,
         SUM(s.executions_delta)         execs,
         SUM(s.rows_processed_delta)     rows_proc,
         SUM(NVL(s.clwait_delta,0))/1e6  cluster_wait_s,
         COUNT(DISTINCT s.plan_hash_value) num_plans
  FROM   dba_hist_sqlstat s
  JOIN   snaps sn
    ON   s.snap_id=sn.snap_id AND s.dbid=sn.dbid
   AND   s.instance_number=sn.instance_number
  GROUP  BY s.sql_id
)
SELECT st.sql_id,
       ROUND(st.elapsed_s,1)                       elapsed_s,
       ROUND(st.cpu_s,1)                           cpu_s,
       st.execs,
       ROUND(st.elapsed_s/NULLIF(st.execs,0),3)    s_per_exec,
       st.buffer_gets,
       ROUND(st.buffer_gets/NULLIF(st.execs,0))    gets_per_exec,
       ROUND(st.rows_proc/NULLIF(st.execs,0))      rows_per_exec,
       ROUND(st.cluster_wait_s,1)                  cluster_wait_s,
       st.num_plans,
       SUBSTR(TRIM(dt.sql_text),1,80)              sql_snippet
FROM   sqlstat st
LEFT JOIN dba_hist_sqltext dt
       ON dt.sql_id = st.sql_id
WHERE  st.execs > 0
ORDER  BY st.buffer_gets DESC          -- candidatos a índice; troque p/ cpu_s/elapsed_s
FETCH FIRST 25 ROWS ONLY;

-- ---------------------------------------------------------------------------
-- Sem Diagnostics Pack (apenas o que está no shared pool agora):
-- ---------------------------------------------------------------------------
-- SELECT sql_id, ROUND(elapsed_time/1e6,1) elapsed_s, executions execs,
--        ROUND(buffer_gets/NULLIF(executions,0)) gets_per_exec, buffer_gets,
--        SUBSTR(sql_text,1,80) sql_snippet
-- FROM   gv$sql WHERE executions > 0
-- ORDER  BY buffer_gets DESC FETCH FIRST 25 ROWS ONLY;
