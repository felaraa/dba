-- =============================================================================
-- audit_global_indexes_on_partitioned.sql
-- Lista índices GLOBAIS (não-locais) sobre tabelas PARTICIONADAS.
-- Índice global em tabela particionada é dívida de manutenção: operações de
-- partição (DROP/TRUNCATE/EXCHANGE) invalidam o índice inteiro.
-- Ajuste a lista de owners no WHERE conforme necessário.
-- =============================================================================

SELECT i.owner,
       i.index_name,
       i.table_owner,
       i.table_name,
       i.partitioned                              AS index_partitioned,
       NVL(pi.locality, 'GLOBAL (non-part)')      AS locality,
       i.status,
       LISTAGG(ic.column_name, ', ')
         WITHIN GROUP (ORDER BY ic.column_position) AS index_columns
FROM   dba_indexes i
JOIN   dba_part_tables pt
       ON pt.owner = i.table_owner
      AND pt.table_name = i.table_name            -- a TABELA é particionada
JOIN   dba_ind_columns ic
       ON ic.index_owner = i.owner
      AND ic.index_name  = i.index_name
LEFT JOIN dba_part_indexes pi
       ON pi.owner = i.owner
      AND pi.index_name = i.index_name
WHERE  NVL(pi.locality, 'GLOBAL') <> 'LOCAL'      -- tudo que NÃO é local = global
  AND  i.table_owner IN ('DBN0_HUA_RAN','DBN0_ERI_RAN','DBN0_EXT_ENRICH')
GROUP  BY i.owner, i.index_name, i.table_owner, i.table_name,
          i.partitioned, NVL(pi.locality,'GLOBAL (non-part)'), i.status
ORDER  BY i.table_owner, i.table_name, i.index_name;

-- Observações:
--  * i.partitioned='NO'              -> índice global não-particionado (mais comum/sensível)
--  * locality='GLOBAL'               -> índice global particionado (chave própria)
--  * status='UNUSABLE'               -> já invalidado por operação de partição
--  * Para globais particionados, o status real por partição está em
--    DBA_IND_PARTITIONS.STATUS.
