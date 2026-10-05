# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""数据修复工具 - 预览/应用/撤销被污染的记忆数据（R7 §6.7）。

按计划 §6.7，本工具专门修复已污染的记忆（错误的 SPACE 归属、错误的
fact_key 关联）。操作分为三个阶段：

1. preview - 扫描数据库，列出待修复记录，不做任何修改
2. apply - 应用修复方案，标记旧记录为 DEPRECATED，写入审计日志
3. revoke - 撤销最近的修复批次，恢复原状

审计日志记录所有修复操作，支持追溯和回滚。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from nonebot import logger

from config import DB_PATH


@dataclass
class RepairRecord:
    """修复记录 - 单个待修复的记忆条目。
    
    Attributes:
        record_id: 记录 ID
        table_name: 表名（memories / memory_candidates）
        issue_type: 问题类型（wrong_space / wrong_fact_key / duplicate）
        current_value: 当前错误值
        proposed_value: 建议修复值
        reason: 问题原因
        affected_user_id: 受影响的用户 ID
        confidence: 修复置信度（0.0-1.0）
    """
    
    record_id: str
    table_name: Literal["memories", "memory_candidates"]
    issue_type: Literal["wrong_space", "wrong_fact_key", "duplicate", "orphan"]
    current_value: str
    proposed_value: str
    reason: str
    affected_user_id: int
    confidence: float


@dataclass
class RepairBatch:
    """修复批次 - 一次修复操作的元数据。
    
    Attributes:
        batch_id: 批次 ID
        repair_count: 修复记录数
        applied_at: 应用时间
        operator: 操作者标识
        rollback_available: 是否可回滚
        audit_log_ids: 审计日志 ID 列表
    """
    
    batch_id: str
    repair_count: int
    applied_at: str
    operator: str
    rollback_available: bool
    audit_log_ids: list[int]


def preview_wrong_space_records(
    conn: sqlite3.Connection,
) -> list[RepairRecord]:
    """预览错误 SPACE 归属的记录（R7 §6.7）。
    
    识别规则：
    - 私聊记忆标记为 SPACE
    - 群聊记忆标记为 PRIVATE_ONLY
    - group_shared_space 不匹配 origin_group_id
    
    Returns:
        待修复记录列表
    """
    records = []
    cursor = conn.cursor()
    
    # 查找私聊记忆标记为 SPACE 的情况
    rows = cursor.execute("""
        SELECT id, audience, owner_type, owner_key, user_id, fact_key
        FROM memories
        WHERE audience = 'SPACE' 
        AND owner_type = 'PERSON'
        AND status != 'DEPRECATED'
    """).fetchall()
    
    for row in rows:
        record_id, audience, owner_type, owner_key, user_id, fact_key = row
        records.append(RepairRecord(
            record_id=str(record_id),
            table_name="memories",
            issue_type="wrong_space",
            current_value=audience,
            proposed_value="PRIVATE_ONLY",
            reason="private_chat_marked_as_space",
            affected_user_id=int(user_id),
            confidence=0.95,
        ))
    
    # 查找群聊记忆标记为 PRIVATE_ONLY 的情况
    rows = cursor.execute("""
        SELECT id, audience, owner_type, owner_key, user_id, fact_key
        FROM memories
        WHERE audience = 'PRIVATE_ONLY'
        AND owner_type = 'SPACE'
        AND status != 'DEPRECATED'
    """).fetchall()
    
    for row in rows:
        record_id, audience, owner_type, owner_key, user_id, fact_key = row
        records.append(RepairRecord(
            record_id=str(record_id),
            table_name="memories",
            issue_type="wrong_space",
            current_value=audience,
            proposed_value="SPACE",
            reason="group_chat_marked_as_private",
            affected_user_id=int(user_id),
            confidence=0.95,
        ))
    
    return records


def preview_duplicate_records(
    conn: sqlite3.Connection,
) -> list[RepairRecord]:
    """预览重复记录（R7 §6.7）。
    
    识别规则：
    - 相同 fact_key 但不同 audience 的记录
    - 相同内容但不同 ID 的记录
    
    Returns:
        待修复记录列表
    """
    records = []
    cursor = conn.cursor()
    
    # 查找同一 fact_key 的多个 audience 副本
    rows = cursor.execute("""
        SELECT fact_key, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
        FROM memories
        WHERE status != 'DEPRECATED'
        GROUP BY fact_key
        HAVING cnt > 1
    """).fetchall()
    
    for row in rows:
        fact_key, cnt, ids = row
        # 保留第一个，标记其余为重复
        id_list = ids.split(',')
        for duplicate_id in id_list[1:]:
            records.append(RepairRecord(
                record_id=str(duplicate_id),
                table_name="memories",
                issue_type="duplicate",
                current_value="ACTIVE",
                proposed_value="DEPRECATED",
                reason=f"duplicate_fact_key:{fact_key}",
                affected_user_id=0,
                confidence=0.90,
            ))
    
    return records


def preview_orphan_candidates(
    conn: sqlite3.Connection,
) -> list[RepairRecord]:
    """预览孤儿候选（source row 已删除）（R7 §6.7）。
    
    Returns:
        待修复记录列表
    """
    records = []
    cursor = conn.cursor()
    
    # 查找 source_conversation_key 指向不存在会话的候选
    rows = cursor.execute("""
        SELECT c.id, c.source_conversation_key, c.user_id, c.fact_key
        FROM memory_candidates c
        WHERE c.status != 'DEPRECATED'
        AND NOT EXISTS (
            SELECT 1 FROM conversation_identity_versions v
            WHERE v.conversation_key = c.source_conversation_key
        )
    """).fetchall()
    
    for row in rows:
        candidate_id, source_key, user_id, fact_key = row
        records.append(RepairRecord(
            record_id=str(candidate_id),
            table_name="memory_candidates",
            issue_type="orphan",
            current_value="ACTIVE",
            proposed_value="DEPRECATED",
            reason=f"source_conversation_missing:{source_key}",
            affected_user_id=int(user_id),
            confidence=0.85,
        ))
    
    return records


def preview_repairs(
    issue_types: list[str] | None = None,
) -> list[RepairRecord]:
    """预览所有待修复记录（R7 §6.7）。
    
    Args:
        issue_types: 限定问题类型，None 表示全部
    
    Returns:
        待修复记录列表
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        all_records = []
        
        if issue_types is None or "wrong_space" in issue_types:
            all_records.extend(preview_wrong_space_records(conn))
        
        if issue_types is None or "duplicate" in issue_types:
            all_records.extend(preview_duplicate_records(conn))
        
        if issue_types is None or "orphan" in issue_types:
            all_records.extend(preview_orphan_candidates(conn))
        
        return all_records
    finally:
        conn.close()


def _create_audit_table(conn: sqlite3.Connection) -> None:
    """创建审计日志表（幂等）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_repair_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            table_name TEXT NOT NULL,
            issue_type TEXT NOT NULL,
            old_value TEXT NOT NULL,
            new_value TEXT NOT NULL,
            reason TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            revoked_at TEXT,
            operator TEXT NOT NULL
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_batch
        ON data_repair_audit(batch_id)
    """)


def apply_repairs(
    records: list[RepairRecord],
    operator: str = "system",
    dry_run: bool = False,
) -> RepairBatch | None:
    """应用修复（R7 §6.7）。
    
    操作步骤：
    1. 创建审计日志表
    2. 开启事务
    3. 对每条记录：
       - 标记旧记录为 DEPRECATED
       - 写入审计日志
    4. 提交事务
    
    Args:
        records: 待修复记录列表
        operator: 操作者标识
        dry_run: 是否仅模拟（不实际修改）
    
    Returns:
        修复批次元数据，失败返回 None
    """
    if not records:
        logger.info("✅ [DataRepair] No records to repair")
        return None
    
    conn = sqlite3.connect(DB_PATH)
    try:
        _create_audit_table(conn)
        
        batch_id = f"repair_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        audit_log_ids = []
        
        conn.execute("BEGIN")
        
        for record in records:
            # 标记为 DEPRECATED
            if record.table_name == "memories":
                conn.execute(
                    "UPDATE memories SET status = 'DEPRECATED', updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (record.record_id,),
                )
            elif record.table_name == "memory_candidates":
                conn.execute(
                    "UPDATE memory_candidates SET status = 'DEPRECATED', updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (record.record_id,),
                )
            
            # 写入审计日志
            cursor = conn.execute(
                "INSERT INTO data_repair_audit "
                "(batch_id, record_id, table_name, issue_type, old_value, new_value, reason, applied_at, operator) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    record.record_id,
                    record.table_name,
                    record.issue_type,
                    record.current_value,
                    record.proposed_value,
                    record.reason,
                    datetime.utcnow().isoformat(),
                    operator,
                ),
            )
            audit_log_ids.append(cursor.lastrowid)
        
        if dry_run:
            conn.execute("ROLLBACK")
            logger.info(f"🧪 [DataRepair] Dry run: would repair {len(records)} records")
            return None
        else:
            conn.execute("COMMIT")
            logger.info(f"✅ [DataRepair] Applied {len(records)} repairs in batch {batch_id}")
            
            return RepairBatch(
                batch_id=batch_id,
                repair_count=len(records),
                applied_at=datetime.utcnow().isoformat(),
                operator=operator,
                rollback_available=True,
                audit_log_ids=audit_log_ids,
            )
    except Exception as e:
        conn.execute("ROLLBACK")
        logger.error(f"❌ [DataRepair] Failed to apply repairs: {e}")
        return None
    finally:
        conn.close()


def revoke_batch(
    batch_id: str,
) -> bool:
    """撤销修复批次（R7 §6.7）。
    
    操作步骤：
    1. 查找批次的所有审计记录
    2. 对每条记录：
       - 恢复旧值
       - 标记审计记录为已撤销
    3. 提交事务
    
    Args:
        batch_id: 批次 ID
    
    Returns:
        是否成功
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("BEGIN")
        
        # 查找批次记录
        rows = conn.execute(
            "SELECT audit_id, record_id, table_name, old_value FROM data_repair_audit "
            "WHERE batch_id = ? AND revoked_at IS NULL",
            (batch_id,),
        ).fetchall()
        
        if not rows:
            logger.warning(f"⚠️ [DataRepair] Batch {batch_id} not found or already revoked")
            conn.execute("ROLLBACK")
            return False
        
        for audit_id, record_id, table_name, old_value in rows:
            # 恢复状态
            if table_name == "memories":
                conn.execute(
                    "UPDATE memories SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (old_value, record_id),
                )
            elif table_name == "memory_candidates":
                conn.execute(
                    "UPDATE memory_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (old_value, record_id),
                )
            
            # 标记审计记录为已撤销
            conn.execute(
                "UPDATE data_repair_audit SET revoked_at = ? WHERE audit_id = ?",
                (datetime.utcnow().isoformat(), audit_id),
            )
        
        conn.execute("COMMIT")
        logger.info(f"✅ [DataRepair] Revoked batch {batch_id} ({len(rows)} records)")
        return True
    except Exception as e:
        conn.execute("ROLLBACK")
        logger.error(f"❌ [DataRepair] Failed to revoke batch {batch_id}: {e}")
        return False
    finally:
        conn.close()


def list_batches() -> list[RepairBatch]:
    """列出所有修复批次。
    
    Returns:
        批次列表（按时间倒序）
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("""
            SELECT batch_id, COUNT(*) as cnt, MIN(applied_at) as applied_at, operator,
                   SUM(CASE WHEN revoked_at IS NULL THEN 1 ELSE 0 END) as active_cnt
            FROM data_repair_audit
            GROUP BY batch_id
            ORDER BY applied_at DESC
        """).fetchall()
        
        batches = []
        for batch_id, cnt, applied_at, operator, active_cnt in rows:
            batches.append(RepairBatch(
                batch_id=batch_id,
                repair_count=cnt,
                applied_at=applied_at,
                operator=operator,
                rollback_available=(active_cnt > 0),
                audit_log_ids=[],
            ))
        
        return batches
    finally:
        conn.close()
