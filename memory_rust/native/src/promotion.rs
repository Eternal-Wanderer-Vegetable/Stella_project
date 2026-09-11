use std::collections::HashSet;

use chrono::{DateTime, NaiveDateTime, Utc};
use rusqlite::{Connection, OptionalExtension, Transaction, TransactionBehavior};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::schema::ensure_supported;
use crate::similarity::{is_similar, merge_content, normalize_text};

#[derive(Clone, Debug, Deserialize)]
pub struct PromotionRequest {
    pub db_path: String,
    pub candidate_id: String,
    pub group_shared_space: String,
    pub user_id: String,
    pub memory_type: String,
    pub quota_limit: usize,
    pub quota_enforce: bool,
    pub quota_confirmation_cap: i64,
    pub quota_weight_importance: f64,
    pub quota_weight_confirmation: f64,
    pub quota_weight_recency: f64,
    pub fts_enabled: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct PromotionOutput {
    pub candidate_id: String,
    pub promoted: bool,
    pub action: String,
    pub memory_id: Option<String>,
    pub archived_count: usize,
    pub conflict_count: usize,
    pub fts_updated: bool,
}

struct Candidate {
    group_shared_space: String,
    user_id: String,
    memory_type: String,
    content: String,
    importance: f64,
    confidence: f64,
    status: String,
    content_raw: String,
    usage_tags: String,
    visibility: String,
    behavior_rule: String,
    source_kind: String,
}

type QuotaRow = (String, Option<f64>, Option<i64>, Option<String>);

fn parse_tags(raw: &str) -> Vec<String> {
    let parsed = serde_json::from_str::<serde_json::Value>(raw).unwrap_or_default();
    parsed
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(serde_json::Value::as_str)
        .map(|item| item.trim().to_uppercase())
        .filter(|item| !item.is_empty())
        .collect()
}

fn merge_tags(old: &str, new: &str) -> String {
    let mut merged = Vec::new();
    for tag in parse_tags(old).into_iter().chain(parse_tags(new)) {
        if !merged.contains(&tag) {
            merged.push(tag);
        }
    }
    serde_json::to_string(&merged).unwrap_or_else(|_| "[]".to_string())
}

fn visibility_rank(value: &str) -> i32 {
    match value.trim().to_uppercase().as_str() {
        "INTERNAL" => 0,
        "RESTRICTED" => 1,
        "CONTEXTUAL" => 2,
        _ => 3,
    }
}

fn merge_visibility(old: &str, new: &str) -> String {
    if visibility_rank(new) <= visibility_rank(old) {
        new.trim().to_uppercase()
    } else {
        old.trim().to_uppercase()
    }
}

fn parse_timestamp(value: &str) -> Option<i64> {
    DateTime::parse_from_rfc3339(value)
        .ok()
        .map(|parsed| parsed.timestamp())
        .or_else(|| {
            NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S")
                .ok()
                .map(|parsed| parsed.and_utc().timestamp())
        })
}

fn quota_score(
    importance: Option<f64>,
    confirmations: Option<i64>,
    last_accessed_at: Option<String>,
    request: &PromotionRequest,
) -> f64 {
    let importance = importance.unwrap_or_default().clamp(0.0, 1.0);
    let confirmations = confirmations.unwrap_or_default().max(0) as f64;
    let confirmation = (confirmations / request.quota_confirmation_cap.max(1) as f64).min(1.0);
    let recency = last_accessed_at
        .and_then(|value| parse_timestamp(&value))
        .map(|timestamp| {
            let age_days = ((Utc::now().timestamp() - timestamp).max(0) as f64) / 86_400.0;
            (-age_days / 30.0).exp()
        })
        .unwrap_or_default();
    request.quota_weight_importance * importance
        + request.quota_weight_confirmation * confirmation
        + request.quota_weight_recency * recency
}

fn chinese_grams(value: &str, min_len: usize, max_len: usize) -> HashSet<String> {
    let chars: Vec<char> = value.chars().collect();
    let mut terms = HashSet::new();
    for start in 0..chars.len() {
        if !('\u{4e00}'..='\u{9fff}').contains(&chars[start]) {
            continue;
        }
        for size in min_len..=max_len {
            if start + size <= chars.len()
                && chars[start..start + size]
                    .iter()
                    .all(|ch| ('\u{4e00}'..='\u{9fff}').contains(ch))
            {
                terms.insert(chars[start..start + size].iter().collect());
            }
        }
    }
    terms
}

fn polarity(value: &str) -> i32 {
    if [
        "不喜欢",
        "不爱",
        "不想",
        "不常",
        "不愿意",
        "讨厌",
        "反感",
        "拒绝",
        "不再",
        "停止",
        "禁止",
        "没兴趣",
    ]
    .iter()
    .any(|word| value.contains(word))
    {
        return -1;
    }
    if [
        "喜欢",
        "爱玩",
        "常玩",
        "经常",
        "愿意",
        "想玩",
        "感兴趣",
        "好",
    ]
    .iter()
    .any(|word| value.contains(word))
    {
        return 1;
    }
    0
}

fn common_terms(left: &str, right: &str) -> bool {
    let left_terms = chinese_grams(left, 2, 4);
    let right_terms = chinese_grams(right, 2, 4);
    if left_terms.iter().any(|term| right_terms.contains(term)) {
        return true;
    }
    let left_words: HashSet<&str> = left
        .split(|ch: char| !ch.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .collect();
    right
        .split(|ch: char| !ch.is_ascii_alphanumeric())
        .filter(|word| !word.is_empty())
        .any(|word| left_words.contains(word))
}

fn contradictory(left: &str, right: &str) -> bool {
    let left_polarity = polarity(left);
    let right_polarity = polarity(right);
    left_polarity != 0
        && right_polarity != 0
        && left_polarity != right_polarity
        && common_terms(left, right)
}

fn fts_text(value: &str) -> String {
    let normalized = normalize_text(value);
    let chars: Vec<char> = normalized.chars().collect();
    let mut tokens = Vec::new();
    let mut index = 0;
    while index < chars.len() {
        if ('\u{4e00}'..='\u{9fff}').contains(&chars[index]) {
            let start = index;
            while index < chars.len() && ('\u{4e00}'..='\u{9fff}').contains(&chars[index]) {
                index += 1;
            }
            for size in [3usize, 2usize] {
                if index - start >= size {
                    for offset in start..=index - size {
                        tokens.push(chars[offset..offset + size].iter().collect::<String>());
                    }
                }
            }
        } else if chars[index].is_ascii_alphanumeric() || chars[index] == '_' {
            let start = index;
            while index < chars.len()
                && (chars[index].is_ascii_alphanumeric() || chars[index] == '_')
            {
                index += 1;
            }
            tokens.push(chars[start..index].iter().collect());
        } else {
            index += 1;
        }
    }
    let mut seen = HashSet::new();
    tokens
        .into_iter()
        .filter(|token| seen.insert(token.clone()))
        .collect::<Vec<_>>()
        .join(" ")
}

fn ensure_fts(tx: &Transaction<'_>) -> rusqlite::Result<()> {
    tx.execute_batch(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
           mem_id UNINDEXED, content, group_shared_space UNINDEXED, user_id UNINDEXED
         )",
    )
}

fn sync_fts(
    tx: &Transaction<'_>,
    request: &PromotionRequest,
    memory_id: &str,
    content: &str,
    group_shared_space: &str,
    user_id: &str,
) -> Result<bool, String> {
    if !request.fts_enabled {
        return Ok(false);
    }
    ensure_fts(tx).map_err(|err| format!("FTS table creation failed: {err}"))?;
    tx.execute("DELETE FROM memories_fts WHERE mem_id = ?", [memory_id])
        .map_err(|err| format!("FTS delete failed: {err}"))?;
    let text = fts_text(content);
    if !text.is_empty() {
        tx.execute(
            "INSERT INTO memories_fts (mem_id, content, group_shared_space, user_id)
             VALUES (?, ?, ?, ?)",
            (memory_id, text, group_shared_space, user_id),
        )
        .map_err(|err| format!("FTS insert failed: {err}"))?;
    }
    Ok(true)
}

fn delete_fts(
    tx: &Transaction<'_>,
    request: &PromotionRequest,
    memory_id: &str,
) -> Result<(), String> {
    if !request.fts_enabled {
        return Ok(());
    }
    ensure_fts(tx).map_err(|err| format!("FTS table creation failed: {err}"))?;
    tx.execute("DELETE FROM memories_fts WHERE mem_id = ?", [memory_id])
        .map_err(|err| format!("FTS delete failed: {err}"))?;
    Ok(())
}

fn load_candidate(
    tx: &Transaction<'_>,
    request: &PromotionRequest,
) -> Result<Option<Candidate>, String> {
    tx.query_row(
        "SELECT group_shared_space, user_id, type, content, importance, confidence, status,
                content_raw, usage_tags, visibility, behavior_rule, source_kind
         FROM memory_candidates WHERE id = ?",
        [&request.candidate_id],
        |row| {
            Ok(Candidate {
                group_shared_space: row.get::<_, Option<String>>(0)?.unwrap_or_default(),
                user_id: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                memory_type: row
                    .get::<_, Option<String>>(2)?
                    .unwrap_or_else(|| "FACT".to_string()),
                content: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
                importance: row.get::<_, Option<f64>>(4)?.unwrap_or_default(),
                confidence: row.get::<_, Option<f64>>(5)?.unwrap_or_default(),
                status: row
                    .get::<_, Option<String>>(6)?
                    .unwrap_or_else(|| "NEW".to_string()),
                content_raw: row.get::<_, Option<String>>(7)?.unwrap_or_default(),
                usage_tags: row
                    .get::<_, Option<String>>(8)?
                    .unwrap_or_else(|| "[]".to_string()),
                visibility: row
                    .get::<_, Option<String>>(9)?
                    .unwrap_or_else(|| "OPEN".to_string()),
                behavior_rule: row.get::<_, Option<String>>(10)?.unwrap_or_default(),
                source_kind: row
                    .get::<_, Option<String>>(11)?
                    .unwrap_or_else(|| "PASSIVE".to_string()),
            })
        },
    )
    .optional()
    .map_err(|err| format!("candidate query failed: {err}"))
}

fn promote_inner(
    tx: &Transaction<'_>,
    request: &PromotionRequest,
    candidate: Candidate,
) -> Result<PromotionOutput, String> {
    if candidate.group_shared_space != request.group_shared_space
        || candidate.user_id != request.user_id
        || candidate.memory_type != request.memory_type
    {
        return Err("promotion scope does not match the candidate row".to_string());
    }
    if !matches!(
        candidate.status.to_uppercase().as_str(),
        "NEW" | "OBSERVING"
    ) {
        return Ok(PromotionOutput {
            candidate_id: request.candidate_id.clone(),
            promoted: false,
            action: "noop".to_string(),
            memory_id: None,
            archived_count: 0,
            conflict_count: 0,
            fts_updated: false,
        });
    }

    let conflicts: Vec<(String, String, f64)> = {
        let mut statement = tx
            .prepare(
                "SELECT id, content, confidence FROM memories
                 WHERE status = 'active' AND group_shared_space = ? AND user_id = ? AND type = ?",
            )
            .map_err(|err| format!("conflict query prepare failed: {err}"))?;
        let rows = statement
            .query_map(
                (
                    &candidate.group_shared_space,
                    &candidate.user_id,
                    &candidate.memory_type,
                ),
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                        row.get::<_, Option<f64>>(2)?.unwrap_or_default(),
                    ))
                },
            )
            .map_err(|err| format!("conflict query failed: {err}"))?;
        rows.collect::<rusqlite::Result<Vec<_>>>()
            .map_err(|err| format!("conflict row failed: {err}"))?
    };
    let mut conflict_count = 0;
    for (memory_id, content, confidence) in conflicts {
        if content != candidate.content && contradictory(&content, &candidate.content) {
            if candidate.confidence >= confidence {
                tx.execute(
                    "UPDATE memories SET status = 'conflict', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    [&memory_id],
                )
                .map_err(|err| format!("conflict update failed: {err}"))?;
                delete_fts(tx, request, &memory_id)?;
                conflict_count += 1;
            } else {
                tx.execute(
                    "UPDATE memory_candidates SET status = 'OBSERVING', updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?",
                    [&request.candidate_id],
                )
                .map_err(|err| format!("candidate observe update failed: {err}"))?;
                return Ok(PromotionOutput {
                    candidate_id: request.candidate_id.clone(),
                    promoted: false,
                    action: "observing_conflict".to_string(),
                    memory_id: None,
                    archived_count: 0,
                    conflict_count: 0,
                    fts_updated: false,
                });
            }
            break;
        }
    }

    let similar_id: Option<String> = {
        let mut statement = tx
            .prepare(
                "SELECT id, content FROM memories
                 WHERE status = 'active' AND group_shared_space = ? AND user_id = ? AND type = ?
                 ORDER BY COALESCE(last_confirmed_at, last_accessed_at) DESC",
            )
            .map_err(|err| format!("similarity query prepare failed: {err}"))?;
        let rows = statement
            .query_map(
                (
                    &candidate.group_shared_space,
                    &candidate.user_id,
                    &candidate.memory_type,
                ),
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .map_err(|err| format!("similarity query failed: {err}"))?;
        let mut found = None;
        for row in rows {
            let (id, content) = row.map_err(|err| format!("similarity row failed: {err}"))?;
            if is_similar(&candidate.content, &content) {
                found = Some(id);
                break;
            }
        }
        found
    };

    let (memory_id, fts_updated) = if let Some(memory_id) = similar_id.as_ref() {
        let row: (String, String, f64, f64, i64, String, String, String) = tx
            .query_row(
                "SELECT content, content_raw, importance, confidence, confirmation_count,
                        usage_tags, visibility, behavior_rule
                 FROM memories WHERE id = ?",
                [memory_id],
                |row| {
                    Ok((
                        row.get::<_, Option<String>>(0)?.unwrap_or_default(),
                        row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                        row.get::<_, Option<f64>>(2)?.unwrap_or_default(),
                        row.get::<_, Option<f64>>(3)?.unwrap_or_default(),
                        row.get::<_, Option<i64>>(4)?.unwrap_or_default(),
                        row.get::<_, Option<String>>(5)?
                            .unwrap_or_else(|| "[]".to_string()),
                        row.get::<_, Option<String>>(6)?
                            .unwrap_or_else(|| "OPEN".to_string()),
                        row.get::<_, Option<String>>(7)?.unwrap_or_default(),
                    ))
                },
            )
            .map_err(|err| format!("similar memory load failed: {err}"))?;
        let merged_content = merge_content(&row.0, &candidate.content);
        let merged_raw = merge_content(
            if row.1.is_empty() { &row.0 } else { &row.1 },
            &candidate.content,
        );
        let merged_visibility = merge_visibility(&row.6, &candidate.visibility);
        let merged_behavior = if candidate.behavior_rule.trim().is_empty() {
            row.7
        } else {
            candidate.behavior_rule.clone()
        };
        tx.execute(
            "UPDATE memories SET content = ?, content_raw = ?, importance = ?, confidence = ?,
                    confirmation_count = ?, last_confirmed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP, usage_tags = ?, visibility = ?,
                    behavior_rule = ? WHERE id = ?",
            (
                &merged_content,
                &merged_raw,
                row.2.max(candidate.importance),
                row.3.max(candidate.confidence),
                row.4 + 1,
                merge_tags(&row.5, &candidate.usage_tags),
                merged_visibility,
                merged_behavior,
                memory_id,
            ),
        )
        .map_err(|err| format!("memory merge failed: {err}"))?;
        let fts_updated = sync_fts(
            tx,
            request,
            memory_id,
            &merged_content,
            &candidate.group_shared_space,
            &candidate.user_id,
        )?;
        (memory_id.clone(), fts_updated)
    } else {
        let memory_id = Uuid::new_v4().simple().to_string();
        tx.execute(
            "INSERT INTO memories (
                id, group_shared_space, user_id, type, content, content_raw, importance, confidence,
                status, confirmation_count, last_confirmed_at, last_accessed_at, compressed_at,
                compression_version, is_atomized, usage_tags, visibility, trigger_data,
                behavior_rule, source_kind
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                       NULL, 0, 0, ?, ?, NULL, ?, ?)",
            (
                &memory_id,
                &candidate.group_shared_space,
                &candidate.user_id,
                &candidate.memory_type,
                &candidate.content,
                if candidate.content_raw.is_empty() {
                    &candidate.content
                } else {
                    &candidate.content_raw
                },
                candidate.importance,
                candidate.confidence,
                &candidate.usage_tags,
                &candidate.visibility,
                &candidate.behavior_rule,
                &candidate.source_kind,
            ),
        )
        .map_err(|err| format!("memory insert failed: {err}"))?;
        let fts_updated = sync_fts(
            tx,
            request,
            &memory_id,
            &candidate.content,
            &candidate.group_shared_space,
            &candidate.user_id,
        )?;
        (memory_id, fts_updated)
    };

    let mut archived_count = 0;
    if similar_id.is_none() {
        let rows: Vec<QuotaRow> = {
            let mut statement = tx
                .prepare(
                    "SELECT id, importance, confirmation_count, last_accessed_at
                     FROM memories WHERE status = 'active' AND group_shared_space = ? AND user_id = ?",
                )
                .map_err(|err| format!("quota query prepare failed: {err}"))?;
            let result = statement
                .query_map((&candidate.group_shared_space, &candidate.user_id), |row| {
                    Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?))
                })
                .map_err(|err| format!("quota query failed: {err}"))?;
            result
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(|err| format!("quota row failed: {err}"))?
        };
        if rows.len() > request.quota_limit {
            let mut scored: Vec<(f64, String)> = rows
                .iter()
                .map(|row| {
                    (
                        quota_score(row.1, row.2, row.3.clone(), request),
                        row.0.clone(),
                    )
                })
                .collect();
            scored.sort_by(|left, right| {
                left.0
                    .total_cmp(&right.0)
                    .then_with(|| left.1.cmp(&right.1))
            });
            let overflow = rows.len() - request.quota_limit;
            if request.quota_enforce {
                for (_, victim_id) in scored.into_iter().take(overflow) {
                    tx.execute(
                        "UPDATE memories SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        [&victim_id],
                    )
                    .map_err(|err| format!("quota archive failed: {err}"))?;
                    delete_fts(tx, request, &victim_id)?;
                    archived_count += 1;
                }
            }
        }
    }

    let changed = tx
        .execute(
            "UPDATE memory_candidates SET status = 'CONFIRMED', updated_at = CURRENT_TIMESTAMP
             WHERE id = ? AND status IN ('NEW', 'OBSERVING')",
            [&request.candidate_id],
        )
        .map_err(|err| format!("candidate confirm update failed: {err}"))?;
    if changed != 1 {
        return Err("candidate changed before confirmation; transaction rolled back".to_string());
    }
    Ok(PromotionOutput {
        candidate_id: request.candidate_id.clone(),
        promoted: true,
        action: if similar_id.is_some() {
            "merge".to_string()
        } else {
            "create".to_string()
        },
        memory_id: Some(memory_id),
        archived_count,
        conflict_count,
        fts_updated,
    })
}

pub fn promote(request: PromotionRequest) -> Result<PromotionOutput, String> {
    let mut conn = Connection::open(&request.db_path)
        .map_err(|err| format!("memory database open failed: {err}"))?;
    ensure_supported(&conn)?;
    let tx = conn
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| format!("promotion transaction begin failed: {err}"))?;
    let candidate = load_candidate(&tx, &request)?;
    let Some(candidate) = candidate else {
        return Ok(PromotionOutput {
            candidate_id: request.candidate_id,
            promoted: false,
            action: "missing".to_string(),
            memory_id: None,
            archived_count: 0,
            conflict_count: 0,
            fts_updated: false,
        });
    };
    let output = promote_inner(&tx, &request, candidate)?;
    tx.commit()
        .map_err(|err| format!("promotion transaction commit failed: {err}"))?;
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::{promote, PromotionRequest};
    use rusqlite::Connection;
    use tempfile::NamedTempFile;

    fn request(path: &std::path::Path, candidate_id: &str) -> PromotionRequest {
        PromotionRequest {
            db_path: path.display().to_string(),
            candidate_id: candidate_id.to_string(),
            group_shared_space: "space".to_string(),
            user_id: "1".to_string(),
            memory_type: "PREFERENCE".to_string(),
            quota_limit: 10,
            quota_enforce: true,
            quota_confirmation_cap: 3,
            quota_weight_importance: 0.4,
            quota_weight_confirmation: 0.3,
            quota_weight_recency: 0.3,
            fts_enabled: true,
        }
    }

    fn setup() -> NamedTempFile {
        let file = NamedTempFile::new().expect("temp db");
        let conn = Connection::open(file.path()).expect("open db");
        conn.execute_batch(
            "CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER);
             INSERT INTO schema_meta (k, version) VALUES ('version', 14);
             CREATE TABLE memory_candidates (
               id TEXT PRIMARY KEY, group_shared_space TEXT, user_id TEXT, type TEXT,
               content TEXT, content_raw TEXT, importance REAL, confidence REAL,
               status TEXT, usage_tags TEXT, visibility TEXT, behavior_rule TEXT,
               source_kind TEXT, updated_at TEXT
             );
             CREATE TABLE memories (
               id TEXT PRIMARY KEY, group_shared_space TEXT, user_id TEXT, type TEXT,
               content TEXT, content_raw TEXT, importance REAL, confidence REAL, status TEXT,
               confirmation_count INTEGER, last_confirmed_at TEXT, last_accessed_at TEXT,
               compressed_at TEXT, compression_version INTEGER, is_atomized INTEGER,
               usage_tags TEXT, visibility TEXT, trigger_data TEXT, behavior_rule TEXT,
               source_kind TEXT, updated_at TEXT
             );
             INSERT INTO memory_candidates
               (id, group_shared_space, user_id, type, content, content_raw, importance,
                confidence, status, usage_tags, visibility, behavior_rule, source_kind)
             VALUES ('c1', 'space', '1', 'PREFERENCE', '喜欢羽毛球', '喜欢羽毛球',
                     .8, .9, 'NEW', '[\"RECOMMEND\"]', 'OPEN', '', 'PASSIVE');",
        )
        .expect("schema");
        file
    }

    #[test]
    fn promotion_commits_memory_and_candidate_atomically() {
        let file = setup();
        let output = promote(request(file.path(), "c1")).expect("promote");
        assert!(output.promoted);
        let conn = Connection::open(file.path()).expect("open");
        let status: String = conn
            .query_row(
                "SELECT status FROM memory_candidates WHERE id = 'c1'",
                [],
                |row| row.get(0),
            )
            .expect("candidate status");
        let memories: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM memories WHERE status = 'active'",
                [],
                |row| row.get(0),
            )
            .expect("memory count");
        let fts: i64 = conn
            .query_row("SELECT COUNT(*) FROM memories_fts", [], |row| row.get(0))
            .expect("fts count");
        assert_eq!(status, "CONFIRMED");
        assert_eq!(memories, 1);
        assert_eq!(fts, 1);
    }

    #[test]
    fn duplicate_invocation_is_a_noop() {
        let file = setup();
        assert!(promote(request(file.path(), "c1")).expect("first").promoted);
        let second = promote(request(file.path(), "c1")).expect("second");
        assert!(!second.promoted);
        assert_eq!(second.action, "noop");
    }

    #[test]
    fn similar_candidate_merges_and_refreshes_fts_once() {
        let file = setup();
        let first = promote(request(file.path(), "c1")).expect("first");
        let conn = Connection::open(file.path()).expect("open");
        conn.execute(
            "INSERT INTO memory_candidates
             (id, group_shared_space, user_id, type, content, content_raw, importance,
              confidence, status, usage_tags, visibility, behavior_rule, source_kind)
             VALUES ('c2', 'space', '1', 'PREFERENCE', '喜欢羽毛球和游泳', '喜欢羽毛球和游泳',
                     .9, .95, 'NEW', '[\"RECOMMEND\"]', 'OPEN', '', 'PASSIVE')",
            [],
        )
        .expect("candidate");
        drop(conn);

        let second = promote(request(file.path(), "c2")).expect("second");
        let conn = Connection::open(file.path()).expect("open");
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM memories WHERE status = 'active'",
                [],
                |row| row.get(0),
            )
            .expect("memory count");
        let content: String = conn
            .query_row(
                "SELECT content FROM memories WHERE id = ?",
                [first.memory_id.as_deref().expect("memory id")],
                |row| row.get(0),
            )
            .expect("content");
        let confirmations: i64 = conn
            .query_row(
                "SELECT confirmation_count FROM memories WHERE id = ?",
                [first.memory_id.as_deref().expect("memory id")],
                |row| row.get(0),
            )
            .expect("confirmations");
        let fts: i64 = conn
            .query_row("SELECT COUNT(*) FROM memories_fts", [], |row| row.get(0))
            .expect("fts count");
        assert!(second.promoted);
        assert_eq!(count, 1);
        assert!(content.contains("游泳"));
        assert_eq!(confirmations, 2);
        assert_eq!(fts, 1);
    }

    #[test]
    fn quota_archives_the_weakest_memory_and_removes_fts() {
        let file = setup();
        let conn = Connection::open(file.path()).expect("open");
        conn.execute(
            "INSERT INTO memories
             (id, group_shared_space, user_id, type, content, content_raw, importance,
              confidence, status, confirmation_count, last_accessed_at, usage_tags, visibility)
             VALUES ('old', 'space', '1', 'PREFERENCE', '喜欢咖啡', '喜欢咖啡', .1, .2,
                     'active', 0, '2020-01-01 00:00:00', '[]', 'OPEN')",
            [],
        )
        .expect("old memory");
        drop(conn);

        let mut promotion_request = request(file.path(), "c1");
        promotion_request.quota_limit = 1;
        let output = promote(promotion_request).expect("promote");
        let conn = Connection::open(file.path()).expect("open");
        let old_status: String = conn
            .query_row("SELECT status FROM memories WHERE id = 'old'", [], |row| {
                row.get(0)
            })
            .expect("old status");
        let active_count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM memories WHERE status = 'active'",
                [],
                |row| row.get(0),
            )
            .expect("active count");
        let fts_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM memories_fts", [], |row| row.get(0))
            .expect("fts count");
        assert!(output.promoted);
        assert_eq!(output.archived_count, 1);
        assert_eq!(old_status, "archived");
        assert_eq!(active_count, 1);
        assert_eq!(fts_count, 1);
    }

    #[test]
    fn lower_confidence_conflict_stays_observing_without_new_memory() {
        let file = setup();
        let conn = Connection::open(file.path()).expect("open");
        conn.execute(
            "UPDATE memory_candidates
             SET content = '用户不喜欢游戏', content_raw = '用户不喜欢游戏'
             WHERE id = 'c1'",
            [],
        )
        .expect("candidate content");
        conn.execute(
            "INSERT INTO memories
             (id, group_shared_space, user_id, type, content, content_raw, importance,
              confidence, status, confirmation_count, usage_tags, visibility)
             VALUES ('old', 'space', '1', 'PREFERENCE', '用户喜欢游戏', '用户喜欢游戏', .8, .95,
                     'active', 1, '[]', 'OPEN')",
            [],
        )
        .expect("old memory");
        drop(conn);

        let output = promote(request(file.path(), "c1")).expect("promote");
        let conn = Connection::open(file.path()).expect("open");
        let candidate_status: String = conn
            .query_row(
                "SELECT status FROM memory_candidates WHERE id = 'c1'",
                [],
                |row| row.get(0),
            )
            .expect("candidate status");
        let memory_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM memories", [], |row| row.get(0))
            .expect("memory count");
        assert!(!output.promoted);
        assert_eq!(output.action, "observing_conflict");
        assert_eq!(candidate_status, "OBSERVING");
        assert_eq!(memory_count, 1);
    }

    #[test]
    fn malformed_fts_rolls_back_the_entire_transaction() {
        let file = setup();
        let conn = Connection::open(file.path()).expect("open");
        conn.execute("CREATE TABLE memories_fts (mem_id TEXT)", [])
            .expect("malformed fts");
        drop(conn);

        let result = promote(request(file.path(), "c1"));
        assert!(result.is_err());
        let conn = Connection::open(file.path()).expect("open");
        let candidate_status: String = conn
            .query_row(
                "SELECT status FROM memory_candidates WHERE id = 'c1'",
                [],
                |row| row.get(0),
            )
            .expect("candidate status");
        let memory_count: i64 = conn
            .query_row("SELECT COUNT(*) FROM memories", [], |row| row.get(0))
            .expect("memory count");
        assert_eq!(candidate_status, "NEW");
        assert_eq!(memory_count, 0);
    }

    #[test]
    fn scope_mismatch_is_rejected_before_writing() {
        let file = setup();
        let mut promotion_request = request(file.path(), "c1");
        promotion_request.user_id = "other-user".to_string();
        let result = promote(promotion_request);
        assert!(result.is_err());
        let conn = Connection::open(file.path()).expect("open");
        let status: String = conn
            .query_row(
                "SELECT status FROM memory_candidates WHERE id = 'c1'",
                [],
                |row| row.get(0),
            )
            .expect("candidate status");
        assert_eq!(status, "NEW");
    }
}
