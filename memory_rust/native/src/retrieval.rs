use std::collections::HashMap;
use std::path::Path;

use rusqlite::{Connection, OpenFlags};
use serde::{Deserialize, Serialize};

use crate::policy::{
    apply_conversation_limit, merge_similar, normalize_mode, rank_memories,
    split_behavior_constraints, MemoryRecord, MODE_CONFLICT_AVOID,
};
use crate::schema::ensure_supported;

#[derive(Clone, Debug, Deserialize)]
pub struct RetrievalRequest {
    pub db_path: String,
    pub group_shared_space: String,
    pub user_id: i64,
    pub query: String,
    pub trigger: String,
    pub mode: String,
    pub pool_limit: usize,
    #[serde(default)]
    pub semantic_scores: HashMap<String, f64>,
    // v2 owner scope（计划 §6.6/§6.7）：全部缺省/空 = SPACE-only legacy 行为。
    // scope 存在时，候选池谓词切换为 owner/audience 下推（不再按
    // group_shared_space 过滤——PERSON 行写在 personal:* 兼容 namespace 里）。
    #[serde(default)]
    pub scope_space_key: String,
    #[serde(default)]
    pub scope_person_owner_key: String,
    #[serde(default)]
    pub scope_subject_key: String,
    #[serde(default)]
    pub scope_person_audiences: Vec<String>,
}

impl RetrievalRequest {
    fn has_person_scope(&self) -> bool {
        !self.scope_space_key.is_empty()
            && !self.scope_person_owner_key.is_empty()
            && !self.scope_subject_key.is_empty()
            && !self.scope_person_audiences.is_empty()
    }

    fn has_scope(&self) -> bool {
        !self.scope_space_key.is_empty()
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct RetrievalOutput {
    pub mode: String,
    pub conversation_memories: Vec<MemoryRecord>,
    pub behavior_constraints: Vec<MemoryRecord>,
    pub trace: serde_json::Value,
}

fn parse_usage_tags(raw: Option<String>) -> Vec<String> {
    let Some(raw) = raw else {
        return Vec::new();
    };
    let value = raw.trim();
    if value.is_empty() {
        return Vec::new();
    }
    let parsed: serde_json::Value = serde_json::from_str(value).unwrap_or_else(|_| {
        serde_json::Value::Array(
            value
                .trim_matches(['[', ']'])
                .split([',', ';', '/'])
                .filter(|item| !item.trim().is_empty())
                .map(|item| serde_json::Value::String(item.trim().to_string()))
                .collect(),
        )
    });
    parsed
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(serde_json::Value::as_str)
        .map(|item| item.trim().to_uppercase())
        .filter(|item| !item.is_empty())
        .collect()
}

fn load_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<MemoryRecord> {
    Ok(MemoryRecord::new(
        row.get(0)?,
        row.get(1)?,
        row.get(2)?,
        row.get::<_, Option<String>>(3)?
            .unwrap_or_else(|| "FACT".to_string()),
        row.get::<_, Option<String>>(4)?.unwrap_or_default(),
        row.get(5)?,
        row.get(6)?,
        row.get::<_, Option<String>>(7)?
            .unwrap_or_else(|| "OPEN".to_string()),
        parse_usage_tags(row.get(8)?),
        row.get(9)?,
        row.get(10)?,
        row.get(11)?,
        row.get(12)?,
    ))
}

fn visibility_params(mode: &str) -> (&'static str, Vec<&'static str>) {
    if normalize_mode(mode) == MODE_CONFLICT_AVOID {
        (
            "(m.visibility IS NULL OR m.visibility != ?)",
            vec!["INTERNAL"],
        )
    } else {
        (
            "(m.visibility IS NULL OR m.visibility NOT IN (?, ?))",
            vec!["RESTRICTED", "INTERNAL"],
        )
    }
}

/// 候选池授权谓词（计划 §6.6）：授权在候选构造阶段下推到 SQL，不是先召回
/// 再过滤。无 scope → legacy 的 space 过滤（行为与 v1 完全一致）；
/// 有 scope → owner/audience 谓词，legacy 行经 COALESCE 兜底（迁移回填前
/// 写入的行 owner_key 为空时按 space 列还原），PERSON 分支只在 scope 声明
/// 了受众时生成——没有受众就没有 PERSON 行。
fn scope_predicate(request: &RetrievalRequest) -> (String, Vec<String>) {
    if !request.has_scope() {
        return (
            " AND m.group_shared_space = ?".to_string(),
            vec![request.group_shared_space.clone()],
        );
    }
    let mut params = vec![request.scope_space_key.clone()];
    let mut person = String::new();
    if request.has_person_scope() {
        let placeholders = vec!["?"; request.scope_person_audiences.len()].join(", ");
        person = format!(
            " OR (m.owner_type = 'PERSON' AND m.owner_key = ? \
             AND m.subject_key = ? AND m.audience IN ({placeholders}))"
        );
        params.push(request.scope_person_owner_key.clone());
        params.push(request.scope_subject_key.clone());
        params.extend(request.scope_person_audiences.iter().cloned());
    }
    (
        format!(
            " AND ((COALESCE(m.owner_type, 'SPACE') = 'SPACE' \
             AND COALESCE(m.owner_key, 'space:' || m.group_shared_space) = ?){person})"
        ),
        params,
    )
}

fn load_candidates(
    conn: &Connection,
    request: &RetrievalRequest,
) -> Result<Vec<MemoryRecord>, String> {
    let (visibility_sql, visibility_values) = visibility_params(&request.mode);
    let user_clause = if request.trigger.eq_ignore_ascii_case("proactive") {
        String::new()
    } else {
        " AND m.user_id = ?".to_string()
    };
    let (scope_sql, mut values) = scope_predicate(request);
    let mut sql = format!(
        "SELECT m.id, m.group_shared_space, m.user_id, m.type, m.content, m.importance,
                m.confidence, m.visibility, m.usage_tags, m.trigger_data, m.behavior_rule,
                m.last_accessed_at, m.last_confirmed_at
         FROM memories m
         WHERE m.status = 'active'{scope_sql}{user_clause}
           AND {visibility_sql}
         ORDER BY COALESCE(m.last_confirmed_at, m.last_accessed_at) DESC, m.id ASC
         LIMIT ?"
    );
    if !user_clause.is_empty() {
        values.push(request.user_id.to_string());
    }
    values.extend(visibility_values.into_iter().map(str::to_string));
    values.push(request.pool_limit.to_string());

    let mut statement = conn
        .prepare(&sql)
        .map_err(|err| format!("candidate query prepare failed: {err}"))?;
    let rows = statement
        .query_map(rusqlite::params_from_iter(values.iter()), load_row)
        .map_err(|err| format!("candidate query failed: {err}"))?;
    let mut candidates = Vec::new();
    for row in rows {
        candidates.push(row.map_err(|err| format!("candidate row failed: {err}"))?);
    }

    if !request.query.trim().is_empty() {
        let fts = load_fts_candidates(conn, request)?;
        if !fts.is_empty() {
            return Ok(fts);
        }
    }
    sql.shrink_to_fit();
    Ok(candidates)
}

fn load_fts_candidates(
    conn: &Connection,
    request: &RetrievalRequest,
) -> Result<Vec<MemoryRecord>, String> {
    let (visibility_sql, visibility_values) = visibility_params(&request.mode);
    let user_clause = if request.trigger.eq_ignore_ascii_case("proactive") {
        String::new()
    } else {
        " AND m.user_id = ?".to_string()
    };
    let (scope_sql, mut values) = scope_predicate(request);
    let sql = format!(
        "SELECT m.id, m.group_shared_space, m.user_id, m.type, m.content, m.importance,
                m.confidence, m.visibility, m.usage_tags, m.trigger_data, m.behavior_rule,
                m.last_accessed_at, m.last_confirmed_at
         FROM memories_fts f
         JOIN memories m ON f.mem_id = m.id
         WHERE m.status = 'active'{scope_sql}{user_clause}
           AND {visibility_sql} AND f.content MATCH ?
         ORDER BY bm25(memories_fts), m.id ASC
         LIMIT ?"
    );
    if !user_clause.is_empty() {
        values.push(request.user_id.to_string());
    }
    values.extend(visibility_values.into_iter().map(str::to_string));
    values.push(request.query.clone());
    values.push(request.pool_limit.to_string());
    let mut statement = match conn.prepare(&sql) {
        Ok(statement) => statement,
        Err(rusqlite::Error::SqliteFailure(error, _))
            if error.extended_code == rusqlite::ffi::SQLITE_ERROR =>
        {
            return Ok(Vec::new());
        }
        Err(err) => return Err(format!("FTS prepare failed: {err}")),
    };
    let rows = statement
        .query_map(rusqlite::params_from_iter(values.iter()), load_row)
        .map_err(|err| format!("FTS query failed: {err}"))?;
    let mut candidates = Vec::new();
    for row in rows {
        candidates.push(row.map_err(|err| format!("FTS row failed: {err}"))?);
    }
    Ok(candidates)
}

pub fn retrieve(request: RetrievalRequest) -> Result<RetrievalOutput, String> {
    let path = Path::new(&request.db_path);
    let conn = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|err| format!("memory database open failed: {err}"))?;
    ensure_supported(&conn)?;
    let mode = normalize_mode(&request.mode).to_string();
    let candidates = load_candidates(&conn, &request)?;
    let ranked = rank_memories(&candidates, &mode, &request.query, &request.semantic_scores);
    let merged = merge_similar(&ranked);
    let (mut conversation, behavior) = split_behavior_constraints(&merged);
    let (limited, threshold_ids) = apply_conversation_limit(&conversation, &mode);
    conversation = limited;
    let conversation_ids: std::collections::HashSet<&str> =
        conversation.iter().map(|item| item.id.as_str()).collect();
    let trace = serde_json::json!({
        "mode": mode,
        "candidate_count": candidates.len(),
        "candidates": candidates.iter().take(10).map(|item| item.id.as_str()).collect::<Vec<_>>(),
        "allowed_count": ranked.len(),
        "ranked_ids": ranked.iter().take(10).map(|item| item.id.as_str()).collect::<Vec<_>>(),
        "merged_count": merged.len(),
        "behavior_count": behavior.len(),
        "final_ids": conversation.iter().map(|item| item.id.as_str()).collect::<Vec<_>>(),
        "rejected_ids": candidates.iter().filter(|item| !conversation_ids.contains(item.id.as_str())).map(|item| item.id.as_str()).collect::<Vec<_>>(),
        "threshold_ids": threshold_ids.into_iter().collect::<Vec<_>>(),
        "ranked_all": merged.iter().map(|item| serde_json::json!({
            "id": item.id,
            "score": item.score.unwrap_or_default(),
            "parts": item.score_parts,
        })).collect::<Vec<_>>(),
    });
    Ok(RetrievalOutput {
        mode,
        conversation_memories: conversation,
        behavior_constraints: behavior,
        trace,
    })
}

#[cfg(test)]
mod tests {
    use super::{retrieve, RetrievalRequest};
    use rusqlite::Connection;
    use tempfile::NamedTempFile;

    fn test_request(db_path: &str, space: &str, user: i64) -> RetrievalRequest {
        RetrievalRequest {
            db_path: db_path.to_string(),
            group_shared_space: space.to_string(),
            user_id: user,
            query: "推荐游戏".to_string(),
            trigger: "reply".to_string(),
            mode: "RECOMMEND".to_string(),
            pool_limit: 20,
            semantic_scores: Default::default(),
            scope_space_key: String::new(),
            scope_person_owner_key: String::new(),
            scope_subject_key: String::new(),
            scope_person_audiences: Vec::new(),
        }
    }

    #[test]
    fn retrieval_respects_space_and_user_scope() {
        let file = NamedTempFile::new().expect("temp db");
        let conn = Connection::open(file.path()).expect("open");
        conn.execute_batch(
            "CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER);
             INSERT INTO schema_meta (k, version) VALUES ('version', 19);
             CREATE TABLE memories (
               id TEXT PRIMARY KEY, group_shared_space TEXT, user_id TEXT, type TEXT,
               content TEXT, importance REAL, confidence REAL, status TEXT,
               usage_tags TEXT, visibility TEXT, trigger_data TEXT, behavior_rule TEXT,
               last_accessed_at TEXT, last_confirmed_at TEXT
             );
             INSERT INTO memories VALUES
               ('ok', 'space-a', '1', 'FACT', '用户喜欢游戏', .8, .9, 'active',
                '[\"RECOMMEND\"]', 'OPEN', NULL, NULL, '2026-09-01 00:00:00', NULL),
               ('wrong-user', 'space-a', '2', 'FACT', '用户喜欢游戏', .8, .9, 'active',
                '[\"RECOMMEND\"]', 'OPEN', NULL, NULL, '2026-09-01 00:00:00', NULL),
               ('wrong-space', 'space-b', '1', 'FACT', '用户喜欢游戏', .8, .9, 'active',
                '[\"RECOMMEND\"]', 'OPEN', NULL, NULL, '2026-09-01 00:00:00', NULL);",
        )
        .expect("schema");
        drop(conn);
        let output = retrieve(test_request(
            &file.path().display().to_string(),
            "space-a",
            1,
        ))
        .expect("retrieve");
        assert_eq!(output.conversation_memories.len(), 1);
        assert_eq!(output.conversation_memories[0].id, "ok");
    }

    #[test]
    fn scope_predicate_returns_space_and_shared_person_rows() {
        // v2 scope：SPACE 行经 COALESCE 兜底命中；USER_SHARED 的 PERSON 行
        // 命中；PRIVATE_ONLY / 他人 PERSON 行绝不出现（计划 §8.1 矩阵）。
        let file = NamedTempFile::new().expect("temp db");
        let conn = Connection::open(file.path()).expect("open");
        conn.execute_batch(
            "CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER);
             INSERT INTO schema_meta (k, version) VALUES ('version', 19);
             CREATE TABLE memories (
               id TEXT PRIMARY KEY, group_shared_space TEXT, user_id TEXT, type TEXT,
               content TEXT, importance REAL, confidence REAL, status TEXT,
               usage_tags TEXT, visibility TEXT, trigger_data TEXT, behavior_rule TEXT,
               last_accessed_at TEXT, last_confirmed_at TEXT,
               owner_type TEXT DEFAULT 'SPACE', owner_key TEXT,
               subject_key TEXT DEFAULT '', audience TEXT DEFAULT 'CURRENT_SPACE'
             );
             INSERT INTO memories VALUES
               ('legacy-space', 'space-a', '2', 'FACT', '旧空间行', .8, .9, 'active',
                '[]', 'OPEN', NULL, NULL, '2026-09-01 00:00:00', NULL,
                NULL, NULL, '', 'CURRENT_SPACE'),
               ('person-shared', 'personal:x', '2', 'FACT', '共享偏好', .8, .9, 'active',
                '[]', 'OPEN', NULL, NULL, '2026-09-01 00:00:00', NULL,
                'PERSON', 'person:qq:10000:2', 'qq:2', 'USER_SHARED'),
               ('person-private', 'personal:y', '2', 'FACT', '私密事实', .8, .9, 'active',
                '[]', 'OPEN', NULL, NULL, '2026-09-01 00:00:00', NULL,
                'PERSON', 'person:qq:10000:2', 'qq:2', 'PRIVATE_ONLY'),
               ('person-other', 'personal:z', '3', 'FACT', '他人事实', .8, .9, 'active',
                '[]', 'OPEN', NULL, NULL, '2026-09-01 00:00:00', NULL,
                'PERSON', 'person:qq:10000:3', 'qq:3', 'USER_SHARED');",
        )
        .expect("schema");
        drop(conn);
        let mut request = test_request(&file.path().display().to_string(), "space-a", 2);
        request.scope_space_key = "space:space-a".to_string();
        request.scope_person_owner_key = "person:qq:10000:2".to_string();
        request.scope_subject_key = "qq:2".to_string();
        request.scope_person_audiences = vec!["USER_SHARED".to_string()];
        let output = retrieve(request).expect("retrieve");
        let ids: Vec<&str> = output
            .conversation_memories
            .iter()
            .map(|m| m.id.as_str())
            .collect();
        assert!(ids.contains(&"legacy-space"));
        assert!(ids.contains(&"person-shared"));
        assert!(!ids.contains(&"person-private"));
        assert!(!ids.contains(&"person-other"));
    }
}
