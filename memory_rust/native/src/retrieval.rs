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
    let mut sql = format!(
        "SELECT m.id, m.group_shared_space, m.user_id, m.type, m.content, m.importance,
                m.confidence, m.visibility, m.usage_tags, m.trigger_data, m.behavior_rule,
                m.last_accessed_at, m.last_confirmed_at
         FROM memories m
         WHERE m.status = 'active' AND m.group_shared_space = ?{user_clause}
           AND {visibility_sql}
         ORDER BY COALESCE(m.last_confirmed_at, m.last_accessed_at) DESC, m.id ASC
         LIMIT ?"
    );
    let mut values: Vec<String> = vec![request.group_shared_space.clone()];
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
    let sql = format!(
        "SELECT m.id, m.group_shared_space, m.user_id, m.type, m.content, m.importance,
                m.confidence, m.visibility, m.usage_tags, m.trigger_data, m.behavior_rule,
                m.last_accessed_at, m.last_confirmed_at
         FROM memories_fts f
         JOIN memories m ON f.mem_id = m.id
         WHERE f.group_shared_space = ? AND m.status = 'active'{user_clause}
           AND {visibility_sql} AND f.content MATCH ?
         ORDER BY bm25(memories_fts), m.id ASC
         LIMIT ?"
    );
    let mut values: Vec<String> = vec![request.group_shared_space.clone()];
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

    #[test]
    fn retrieval_respects_space_and_user_scope() {
        let file = NamedTempFile::new().expect("temp db");
        let conn = Connection::open(file.path()).expect("open");
        conn.execute_batch(
            "CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER);
             INSERT INTO schema_meta (k, version) VALUES ('version', 14);
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
        let output = retrieve(RetrievalRequest {
            db_path: file.path().display().to_string(),
            group_shared_space: "space-a".to_string(),
            user_id: 1,
            query: "推荐游戏".to_string(),
            trigger: "reply".to_string(),
            mode: "RECOMMEND".to_string(),
            pool_limit: 20,
            semantic_scores: Default::default(),
        })
        .expect("retrieve");
        assert_eq!(output.conversation_memories.len(), 1);
        assert_eq!(output.conversation_memories[0].id, "ok");
    }
}
