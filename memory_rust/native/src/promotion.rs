use std::collections::{BTreeMap, HashSet};

use chrono::{DateTime, NaiveDateTime, Utc};
use rusqlite::{types::ValueRef, Connection, OptionalExtension, Transaction, TransactionBehavior};
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use sha2::{Digest, Sha256};
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
    // v2 owner 归属（计划 §6.5/§6.7）：留空时回退候选行自身的 owner 列
    // （再回退 legacy SPACE 语义）。晋升/相似/配额全部按 owner 生效值收口，
    // PERSON 记忆不会跟空间记忆抢同一份配额，也不会互相合并。
    #[serde(default)]
    pub owner_type: String,
    #[serde(default)]
    pub owner_key: String,
    #[serde(default)]
    pub subject_key: String,
    #[serde(default)]
    pub audience: String,
    #[serde(default)]
    pub source_conversation_key: String,
    #[serde(default)]
    pub fact_key: String,
    #[serde(default)]
    pub policy_version: String,
    #[serde(default)]
    pub cas_schema_version: i64,
    #[serde(default)]
    pub expected_scope_versions: BTreeMap<String, i64>,
    #[serde(default)]
    pub expected_evidence_digest: String,
    #[serde(default)]
    pub expected_candidate_digest: String,
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
    owner_type: String,
    owner_key: String,
    subject_key: String,
    audience: String,
    source_conversation_key: String,
    fact_key: String,
    policy_version: String,
    occurrence_count: i64,
    source_kinds: String,
    source_message_ids: String,
}

/// 晋升事务内使用的生效 owner：请求显式提供时以请求为准，否则回退候选行
/// （再回退 legacy SPACE 语义）。相似/冲突/配额/INSERT 全部用它。
struct EffectiveOwner {
    owner_type: String,
    owner_key: String,
    subject_key: String,
    audience: String,
    source_conversation_key: String,
    fact_key: String,
    policy_version: String,
}

fn effective_owner(request: &PromotionRequest, candidate: &Candidate) -> EffectiveOwner {
    let owner_type = if request.owner_type.is_empty() {
        if candidate.owner_type.is_empty() {
            "SPACE".to_string()
        } else {
            candidate.owner_type.clone()
        }
    } else {
        request.owner_type.clone()
    };
    let owner_key = if request.owner_key.is_empty() {
        if candidate.owner_key.is_empty() {
            format!("space:{}", candidate.group_shared_space)
        } else {
            candidate.owner_key.clone()
        }
    } else {
        request.owner_key.clone()
    };
    EffectiveOwner {
        owner_type,
        owner_key,
        subject_key: if request.subject_key.is_empty() {
            candidate.subject_key.clone()
        } else {
            request.subject_key.clone()
        },
        audience: if request.audience.is_empty() {
            if candidate.audience.is_empty() {
                "CURRENT_SPACE".to_string()
            } else {
                candidate.audience.clone()
            }
        } else {
            request.audience.clone()
        },
        source_conversation_key: if request.source_conversation_key.is_empty() {
            candidate.source_conversation_key.clone()
        } else {
            request.source_conversation_key.clone()
        },
        fact_key: if request.fact_key.is_empty() {
            candidate.fact_key.clone()
        } else {
            request.fact_key.clone()
        },
        policy_version: if request.policy_version.is_empty() {
            candidate.policy_version.clone()
        } else {
            request.policy_version.clone()
        },
    }
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
    conn: &Connection,
    request: &PromotionRequest,
) -> Result<Option<Candidate>, String> {
    conn.query_row(
        "SELECT group_shared_space, user_id, type, content, importance, confidence, status,
                content_raw, usage_tags, visibility, behavior_rule, source_kind,
                owner_type, owner_key, subject_key, audience,
                source_conversation_key, fact_key, policy_version,
                COALESCE(occurrence_count, 1), COALESCE(source_kinds, '[\"PASSIVE\"]'),
                COALESCE(source_message_ids, '[]')
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
                owner_type: row.get::<_, Option<String>>(12)?.unwrap_or_default(),
                owner_key: row.get::<_, Option<String>>(13)?.unwrap_or_default(),
                subject_key: row.get::<_, Option<String>>(14)?.unwrap_or_default(),
                audience: row
                    .get::<_, Option<String>>(15)?
                    .unwrap_or_else(|| "CURRENT_SPACE".to_string()),
                source_conversation_key: row.get::<_, Option<String>>(16)?.unwrap_or_default(),
                fact_key: row.get::<_, Option<String>>(17)?.unwrap_or_default(),
                policy_version: row.get::<_, Option<String>>(18)?.unwrap_or_default(),
                occurrence_count: row.get::<_, Option<i64>>(19)?.unwrap_or(1),
                source_kinds: row
                    .get::<_, Option<String>>(20)?
                    .unwrap_or_else(|| "[\"PASSIVE\"]".to_string()),
                source_message_ids: row
                    .get::<_, Option<String>>(21)?
                    .unwrap_or_else(|| "[]".to_string()),
            })
        },
    )
    .optional()
    .map_err(|err| format!("candidate query failed: {err}"))
}

fn digest_hex(domain: &[u8], payload: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(domain);
    hasher.update(payload);
    hasher
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

enum CasValue<'a> {
    #[allow(dead_code)]
    // The wire format reserves an explicit null tag; current CAS fields are non-null.
    Null,
    Text(&'a str),
    Integer(i64),
    Float(f64),
    Boolean(bool),
}

fn append_cas_field(output: &mut Vec<u8>, name: &str, value: CasValue<'_>) -> Result<(), String> {
    let name = name.as_bytes();
    output.extend_from_slice(&(name.len() as u64).to_be_bytes());
    output.extend_from_slice(name);
    let (tag, payload): (u8, Vec<u8>) = match value {
        CasValue::Null => (b'n', Vec::new()),
        CasValue::Text(text) => (b's', text.as_bytes().to_vec()),
        CasValue::Integer(number) => (b'i', number.to_be_bytes().to_vec()),
        CasValue::Float(number) => {
            if !number.is_finite() {
                return Err("CAS float must be finite".to_string());
            }
            let normalized = if number == 0.0 { 0.0 } else { number };
            (b'f', normalized.to_be_bytes().to_vec())
        }
        CasValue::Boolean(value) => (b'b', vec![u8::from(value)]),
    };
    output.push(tag);
    output.extend_from_slice(&(payload.len() as u64).to_be_bytes());
    output.extend_from_slice(&payload);
    Ok(())
}

fn digest_cas_object(
    object_type: &str,
    fields: Vec<(&str, CasValue<'_>)>,
) -> Result<String, String> {
    let kind = object_type.as_bytes();
    if !kind.is_ascii() {
        return Err("CAS object type must be ASCII".to_string());
    }
    let mut bytes = b"stella-cas-v1\0".to_vec();
    bytes.extend_from_slice(kind);
    bytes.push(0);
    bytes.extend_from_slice(&(fields.len() as u64).to_be_bytes());
    for (name, value) in fields {
        append_cas_field(&mut bytes, name, value)?;
    }
    Ok(digest_hex(b"", &bytes))
}

struct EvidenceDigestRow {
    id: String,
    source_row_id: i64,
    source_conversation_key: String,
    source_digest: String,
    fact_subject_key: String,
    owner_key: String,
    audience: String,
    fact_key: String,
    verification_status: String,
    assessment_version: String,
    provenance_json: String,
}

fn evidence_set_digest(rows: &[EvidenceDigestRow]) -> Result<String, String> {
    let mut ordered: Vec<&EvidenceDigestRow> = rows.iter().collect();
    ordered.sort_by(|left, right| left.id.as_bytes().cmp(right.id.as_bytes()));
    let mut fields = vec![("evidence_count", CasValue::Integer(ordered.len() as i64))];
    for row in ordered {
        fields.extend([
            ("evidence.id", CasValue::Text(&row.id)),
            (
                "evidence.source_row_id",
                CasValue::Integer(row.source_row_id),
            ),
            (
                "evidence.source_conversation_key",
                CasValue::Text(&row.source_conversation_key),
            ),
            ("evidence.source_digest", CasValue::Text(&row.source_digest)),
            (
                "evidence.fact_subject_key",
                CasValue::Text(&row.fact_subject_key),
            ),
            ("evidence.owner_key", CasValue::Text(&row.owner_key)),
            ("evidence.audience", CasValue::Text(&row.audience)),
            ("evidence.fact_key", CasValue::Text(&row.fact_key)),
            (
                "evidence.verification_status",
                CasValue::Text(&row.verification_status),
            ),
            (
                "evidence.assessment_version",
                CasValue::Text(&row.assessment_version),
            ),
            ("evidence.candidate_link_active", CasValue::Boolean(true)),
            ("evidence.claim_state_active", CasValue::Boolean(true)),
        ]);
    }
    digest_cas_object("evidence_set", fields)
}

fn candidate_cas_digest(
    candidate_id: &str,
    candidate: &Candidate,
    owner: &EffectiveOwner,
    verification_status: &str,
    evidence_digest: &str,
) -> Result<String, String> {
    digest_cas_object(
        "promotion_candidate",
        vec![
            ("candidate_id", CasValue::Text(candidate_id)),
            (
                "group_shared_space",
                CasValue::Text(&candidate.group_shared_space),
            ),
            ("user_id", CasValue::Text(&candidate.user_id)),
            ("memory_type", CasValue::Text(&candidate.memory_type)),
            ("content", CasValue::Text(&candidate.content)),
            ("status", CasValue::Text(&candidate.status)),
            ("importance", CasValue::Float(candidate.importance)),
            ("confidence", CasValue::Float(candidate.confidence)),
            (
                "occurrence_count",
                CasValue::Integer(candidate.occurrence_count),
            ),
            ("source_kinds", CasValue::Text(&candidate.source_kinds)),
            ("source_kind", CasValue::Text(&candidate.source_kind)),
            (
                "source_message_ids",
                CasValue::Text(&candidate.source_message_ids),
            ),
            ("owner_type", CasValue::Text(&owner.owner_type)),
            ("owner_key", CasValue::Text(&owner.owner_key)),
            ("subject_key", CasValue::Text(&owner.subject_key)),
            ("audience", CasValue::Text(&owner.audience)),
            (
                "source_conversation_key",
                CasValue::Text(&owner.source_conversation_key),
            ),
            ("fact_key", CasValue::Text(&owner.fact_key)),
            ("policy_version", CasValue::Text(&owner.policy_version)),
            ("usage_tags", CasValue::Text(&candidate.usage_tags)),
            ("visibility", CasValue::Text(&candidate.visibility)),
            ("behavior_rule", CasValue::Text(&candidate.behavior_rule)),
            ("verification_status", CasValue::Text(verification_status)),
            ("evidence_digest", CasValue::Text(evidence_digest)),
        ],
    )
}

fn snapshot_digest(snapshot: &JsonValue) -> Result<String, String> {
    let bytes = serde_json::to_vec(snapshot)
        .map_err(|err| format!("source snapshot serialization failed: {err}"))?;
    Ok(digest_hex(b"stella-memory-source-v1\0", &bytes))
}

fn source_column_value(name: &str, value: ValueRef<'_>) -> Result<JsonValue, String> {
    if matches!(name, "id" | "part_index") {
        let value = match value {
            ValueRef::Null => 0,
            ValueRef::Integer(number) => number,
            ValueRef::Real(number) => number as i64,
            ValueRef::Text(bytes) => std::str::from_utf8(bytes)
                .map_err(|_| "source integer column is not UTF-8".to_string())?
                .parse::<i64>()
                .map_err(|_| "source integer column is invalid".to_string())?,
            ValueRef::Blob(_) => return Err("source integer column is a blob".to_string()),
        };
        return Ok(JsonValue::from(value));
    }
    let value = match value {
        ValueRef::Null => String::new(),
        ValueRef::Integer(number) => number.to_string(),
        ValueRef::Real(number) => number.to_string(),
        ValueRef::Text(bytes) => std::str::from_utf8(bytes)
            .map_err(|_| "source text column is not UTF-8".to_string())?
            .to_string(),
        ValueRef::Blob(_) => return Err("source text column is a blob".to_string()),
    };
    Ok(JsonValue::String(value))
}

fn source_snapshot_is_current(
    tx: &Transaction<'_>,
    snapshot: &JsonValue,
    expected_digest: &str,
) -> Result<bool, String> {
    const SOURCE_COLUMNS: &[&str] = &[
        "id",
        "group_id",
        "user_id",
        "content",
        "source_kind",
        "timestamp",
        "msg_id",
        "conversation_key",
        "bot_id",
        "reply_to_msg_id",
        "reply_target_user_id",
        "mentioned_user_ids_json",
        "logical_message_id",
        "part_index",
        "origin_msg_id",
        "reply_recipient_user_id",
    ];
    let Some(object) = snapshot.as_object() else {
        return Ok(false);
    };
    if !object.contains_key("id") || !object.contains_key("group_id") {
        return Ok(false);
    }
    let keys: Vec<String> = object.keys().cloned().collect();
    if keys
        .iter()
        .any(|key| !SOURCE_COLUMNS.contains(&key.as_str()))
    {
        return Ok(false);
    }
    let columns: HashSet<String> = {
        let mut statement = tx
            .prepare("PRAGMA table_info(group_messages)")
            .map_err(|err| format!("source schema query failed: {err}"))?;
        let rows = statement
            .query_map([], |row| row.get::<_, String>(1))
            .map_err(|err| format!("source schema read failed: {err}"))?;
        rows.collect::<rusqlite::Result<HashSet<_>>>()
            .map_err(|err| format!("source schema row failed: {err}"))?
    };
    if keys.iter().any(|key| !columns.contains(key)) {
        return Ok(false);
    }
    let Some(source_id) = object.get("id").and_then(JsonValue::as_i64) else {
        return Ok(false);
    };
    let Some(group_id) = object.get("group_id").and_then(JsonValue::as_str) else {
        return Ok(false);
    };
    let select = keys
        .iter()
        .map(|key| format!("\"{key}\""))
        .collect::<Vec<_>>()
        .join(", ");
    let sql = format!("SELECT {select} FROM group_messages WHERE id = ? AND group_id = ?");
    let current = tx
        .query_row(&sql, (source_id, group_id), |row| {
            let mut values = serde_json::Map::new();
            for (index, name) in keys.iter().enumerate() {
                let value = source_column_value(name, row.get_ref(index)?).map_err(|err| {
                    rusqlite::Error::FromSqlConversionFailure(
                        index,
                        rusqlite::types::Type::Text,
                        Box::new(std::io::Error::other(err)),
                    )
                })?;
                values.insert(name.clone(), value);
            }
            Ok(JsonValue::Object(values))
        })
        .optional()
        .map_err(|err| format!("source row query failed: {err}"))?;
    let Some(current) = current else {
        return Ok(false);
    };
    if &current != snapshot {
        return Ok(false);
    }
    Ok(snapshot_digest(snapshot)? == expected_digest)
}

fn verify_candidate_evidence(
    tx: &Transaction<'_>,
    request: &PromotionRequest,
    candidate: &Candidate,
    owner: &EffectiveOwner,
) -> Result<&'static str, String> {
    if request.cas_schema_version != 1
        || request.expected_scope_versions.len() != 2
        || request.expected_evidence_digest.is_empty()
        || request.expected_candidate_digest.is_empty()
    {
        return Ok("evidence_cas_missing");
    }
    for scope_key in [owner.owner_key.as_str(), "global"] {
        let Some(expected_version) = request.expected_scope_versions.get(scope_key) else {
            return Ok("scope_versions_missing");
        };
        let current_version: i64 = tx
            .query_row(
                "SELECT COALESCE((SELECT version FROM memory_scope_versions WHERE scope_key = ?), 0)",
                [scope_key],
                |row| row.get(0),
            )
            .map_err(|err| format!("scope version query failed: {err}"))?;
        if current_version != *expected_version {
            return Ok("scope_versions_changed");
        }
    }

    let raw_rows: Vec<(
        String,
        i64,
        String,
        String,
        String,
        String,
        String,
        String,
        String,
        String,
    )> = {
        let mut statement = tx
            .prepare(concat!(
                "SELECT e.id, e.source_row_id, e.source_conversation_key, e.source_digest, ",
                "e.fact_subject_key, e.owner_key, e.audience, e.fact_key, ",
                "e.verification_status, e.provenance_json FROM memory_evidence e ",
                "JOIN memory_claim_links l ON l.evidence_id = e.id ",
                "JOIN memory_claim_links s ON s.owner_key = e.owner_key ",
                "AND s.audience = e.audience AND s.entity_type = 'claim_state' ",
                "AND s.entity_id = e.fact_key AND s.claim_key = e.fact_key ",
                "AND s.projection_slot = 'eligibility' AND s.status = 'active' ",
                "WHERE e.candidate_id = ? AND e.owner_key = ? AND e.audience = ? ",
                "AND e.fact_key = ? AND e.verification_status = 'accepted' ",
                "AND l.entity_type = 'memory_candidate' AND l.entity_id = ? ",
                "AND l.claim_key = e.fact_key AND l.projection_slot = 'candidate' ",
                "AND l.status = 'active' ORDER BY e.id"
            ))
            .map_err(|err| format!("accepted evidence query prepare failed: {err}"))?;
        let mapped = statement
            .query_map(
                (
                    &request.candidate_id,
                    &owner.owner_key,
                    &owner.audience,
                    &owner.fact_key,
                    &request.candidate_id,
                ),
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, i64>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                        row.get::<_, String>(5)?,
                        row.get::<_, String>(6)?,
                        row.get::<_, String>(7)?,
                        row.get::<_, String>(8)?,
                        row.get::<_, String>(9)?,
                    ))
                },
            )
            .map_err(|err| format!("accepted evidence query failed: {err}"))?;
        mapped
            .collect::<rusqlite::Result<Vec<_>>>()
            .map_err(|err| format!("accepted evidence row failed: {err}"))?
    };
    if raw_rows.is_empty() {
        return Ok("accepted_evidence_missing");
    }
    let mut rows: Vec<EvidenceDigestRow> = raw_rows
        .into_iter()
        .map(|row| EvidenceDigestRow {
            id: row.0,
            source_row_id: row.1,
            source_conversation_key: row.2,
            source_digest: row.3,
            fact_subject_key: row.4,
            owner_key: row.5,
            audience: row.6,
            fact_key: row.7,
            verification_status: row.8,
            assessment_version: String::new(),
            provenance_json: row.9,
        })
        .collect();
    for row in &mut rows {
        let provenance: JsonValue = serde_json::from_str(&row.provenance_json)
            .map_err(|_| "accepted evidence provenance is malformed".to_string())?;
        row.assessment_version = provenance
            .get("assessment_version")
            .and_then(JsonValue::as_str)
            .unwrap_or_default()
            .to_string();
    }
    let evidence_digest = evidence_set_digest(&rows)?;
    if evidence_digest != request.expected_evidence_digest {
        return Ok("evidence_set_changed");
    }

    let expected_subject = format!("qq:{}", candidate.user_id);
    for row in &rows {
        let provenance: JsonValue = match serde_json::from_str(&row.provenance_json) {
            Ok(value) => value,
            Err(_) => return Ok("accepted_evidence_malformed"),
        };
        let Some(snapshot) = provenance.get("source_snapshot") else {
            return Ok("source_snapshot_missing");
        };
        let source_kind = snapshot
            .get("source_kind")
            .and_then(JsonValue::as_str)
            .unwrap_or("PASSIVE")
            .to_uppercase();
        let bot_id = snapshot
            .get("bot_id")
            .and_then(JsonValue::as_str)
            .unwrap_or_default();
        let source_id = snapshot.get("id").and_then(JsonValue::as_i64);
        if provenance
            .get("assessment_version")
            .and_then(JsonValue::as_str)
            != Some("2026-10-08.1")
            || provenance
                .get("verification_status")
                .and_then(JsonValue::as_str)
                != Some("accepted")
            || provenance.get("claim_key").and_then(JsonValue::as_str)
                != Some(owner.fact_key.as_str())
            || provenance
                .get("recording_author_key")
                .and_then(JsonValue::as_str)
                != Some(expected_subject.as_str())
            || provenance
                .get("fact_object_key")
                .and_then(JsonValue::as_str)
                != Some(expected_subject.as_str())
            || provenance
                .get("exact_support_span")
                .and_then(JsonValue::as_str)
                != Some(candidate.content.as_str())
            || provenance
                .get("conversation_key")
                .and_then(JsonValue::as_str)
                != Some(row.source_conversation_key.as_str())
            || provenance.get("source_id").and_then(JsonValue::as_i64) != Some(row.source_row_id)
            || source_id != Some(row.source_row_id)
            || snapshot.get("user_id").and_then(JsonValue::as_str)
                != Some(candidate.user_id.as_str())
            || snapshot.get("content").and_then(JsonValue::as_str)
                != Some(candidate.content.as_str())
            || snapshot.get("conversation_key").and_then(JsonValue::as_str)
                != Some(row.source_conversation_key.as_str())
            || snapshot.get("bot_id").and_then(JsonValue::as_str) != Some(bot_id)
            || bot_id.is_empty()
            || !matches!(
                source_kind.as_str(),
                "AT_MENTION" | "PASSIVE" | "PRIVATE_DIRECT"
            )
            || row.fact_subject_key != expected_subject
        {
            return Ok("accepted_evidence_scope_mismatch");
        }
        if !source_snapshot_is_current(tx, snapshot, &row.source_digest)? {
            return Ok("source_snapshot_changed");
        }
    }
    if candidate_cas_digest(
        &request.candidate_id,
        candidate,
        owner,
        "accepted",
        &evidence_digest,
    )? != request.expected_candidate_digest
    {
        return Ok("candidate_changed");
    }
    Ok("accepted")
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
    let owner = effective_owner(request, &candidate);
    let evidence_status = verify_candidate_evidence(tx, request, &candidate, &owner)?;
    if evidence_status != "accepted" {
        return Ok(PromotionOutput {
            candidate_id: request.candidate_id.clone(),
            promoted: false,
            action: evidence_status.to_string(),
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
                 WHERE status = 'active' AND user_id = ? AND type = ?
                   AND COALESCE(owner_type, 'SPACE') = ?
                   AND COALESCE(owner_key, 'space:' || group_shared_space) = ?",
            )
            .map_err(|err| format!("conflict query prepare failed: {err}"))?;
        let rows = statement
            .query_map(
                (
                    &candidate.user_id,
                    &candidate.memory_type,
                    &owner.owner_type,
                    &owner.owner_key,
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
                 WHERE status = 'active' AND user_id = ? AND type = ?
                   AND COALESCE(owner_type, 'SPACE') = ?
                   AND COALESCE(owner_key, 'space:' || group_shared_space) = ?
                 ORDER BY COALESCE(last_confirmed_at, last_accessed_at) DESC",
            )
            .map_err(|err| format!("similarity query prepare failed: {err}"))?;
        let rows = statement
            .query_map(
                (
                    &candidate.user_id,
                    &candidate.memory_type,
                    &owner.owner_type,
                    &owner.owner_key,
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
                behavior_rule, source_kind,
                owner_type, owner_key, subject_key, audience,
                source_conversation_key, fact_key, policy_version
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                       NULL, 0, 0, ?, ?, NULL, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?)",
            rusqlite::params![
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
                &owner.owner_type,
                &owner.owner_key,
                &owner.subject_key,
                &owner.audience,
                &owner.source_conversation_key,
                &owner.fact_key,
                &owner.policy_version,
            ],
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
                     FROM memories WHERE status = 'active' AND user_id = ?
                       AND COALESCE(owner_type, 'SPACE') = ?
                       AND COALESCE(owner_key, 'space:' || group_shared_space) = ?",
                )
                .map_err(|err| format!("quota query prepare failed: {err}"))?;
            let result = statement
                .query_map(
                    (&candidate.user_id, &owner.owner_type, &owner.owner_key),
                    |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
                )
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

    let linked_evidence: Vec<(String, String)> = {
        let mut statement = tx
            .prepare(concat!(
                "SELECT e.id, e.source_digest FROM memory_evidence e ",
                "JOIN memory_claim_links l ON l.evidence_id = e.id ",
                "JOIN memory_claim_links s ON s.owner_key = e.owner_key ",
                "AND s.audience = e.audience AND s.entity_type = 'claim_state' ",
                "AND s.entity_id = e.fact_key AND s.claim_key = e.fact_key ",
                "AND s.projection_slot = 'eligibility' AND s.status = 'active' ",
                "WHERE e.candidate_id = ? AND e.owner_key = ? AND e.audience = ? ",
                "AND e.fact_key = ? AND e.verification_status = 'accepted' ",
                "AND l.entity_type = 'memory_candidate' AND l.entity_id = ? ",
                "AND l.claim_key = e.fact_key AND l.projection_slot = 'candidate' ",
                "AND l.status = 'active' ORDER BY e.id"
            ))
            .map_err(|err| format!("promoted lineage query prepare failed: {err}"))?;
        let rows = statement
            .query_map(
                (
                    &request.candidate_id,
                    &owner.owner_key,
                    &owner.audience,
                    &owner.fact_key,
                    &request.candidate_id,
                ),
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .map_err(|err| format!("promoted lineage query failed: {err}"))?;
        rows.collect::<rusqlite::Result<Vec<_>>>()
            .map_err(|err| format!("promoted lineage row failed: {err}"))?
    };
    for (evidence_id, source_digest) in linked_evidence {
        tx.execute(
            "INSERT OR IGNORE INTO memory_claim_links (
                id, evidence_id, owner_key, audience, entity_type, entity_id, claim_key,
                projection_slot, projection_version, slot_digest, status
             ) VALUES (?, ?, ?, ?, 'memory', ?, ?, 'memory', 1, ?, 'active')",
            (
                Uuid::new_v4().simple().to_string(),
                evidence_id,
                &owner.owner_key,
                &owner.audience,
                &memory_id,
                &owner.fact_key,
                source_digest,
            ),
        )
        .map_err(|err| format!("promoted lineage insert failed: {err}"))?;
    }

    for scope_key in [owner.owner_key.as_str(), "global"] {
        tx.execute(
            concat!(
                "INSERT INTO memory_scope_versions (scope_key, version, updated_at) ",
                "VALUES (?, 1, CURRENT_TIMESTAMP) ",
                "ON CONFLICT(scope_key) DO UPDATE SET ",
                "version = version + 1, updated_at = CURRENT_TIMESTAMP"
            ),
            [scope_key],
        )
        .map_err(|err| format!("promotion scope bump failed: {err}"))?;
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
    use super::{
        candidate_cas_digest, digest_cas_object, effective_owner, evidence_set_digest,
        load_candidate, promote, snapshot_digest, CasValue, EffectiveOwner, EvidenceDigestRow,
        PromotionRequest,
    };
    use rusqlite::Connection;
    use serde_json::{json, Value as JsonValue};
    use std::collections::BTreeMap;
    use tempfile::NamedTempFile;

    #[test]
    fn typed_cas_scalar_golden_vector_matches_python() {
        assert_eq!(
            digest_cas_object(
                "parity_fixture",
                vec![
                    ("null", CasValue::Null),
                    ("flag", CasValue::Boolean(true)),
                    ("signed", CasValue::Integer(-42)),
                    ("float", CasValue::Float(-0.0)),
                    ("text", CasValue::Text("偏好/é")),
                ],
            )
            .expect("CAS fixture digest"),
            "4e04306101fb4a12abbafa7fda468398cb1dfef05a2b5a1bcdd2556e857b85ed"
        );
    }

    #[test]
    fn evidence_set_golden_vector_matches_python() {
        let row = EvidenceDigestRow {
            id: "e-2".to_string(),
            source_row_id: 2,
            source_conversation_key: "conv".to_string(),
            source_digest: "a".repeat(64),
            fact_subject_key: "qq:7".to_string(),
            owner_key: "space:1".to_string(),
            audience: "CURRENT_SPACE".to_string(),
            fact_key: "claim:v1:x".to_string(),
            verification_status: "accepted".to_string(),
            assessment_version: "2026-10-08.1".to_string(),
            provenance_json: "{}".to_string(),
        };
        assert_eq!(
            evidence_set_digest(&[row]).expect("evidence digest"),
            "8a74529eb1d8f50a173f638cebd941af07a297fef8500b7bab61ce78dec15a22"
        );
    }

    #[test]
    fn candidate_digest_golden_vector_matches_python() {
        let candidate = super::Candidate {
            group_shared_space: "1".to_string(),
            user_id: "7".to_string(),
            memory_type: "PREFERENCE".to_string(),
            content: "我喜欢桌游".to_string(),
            importance: 0.7,
            confidence: 0.8,
            status: "NEW".to_string(),
            content_raw: "我喜欢桌游".to_string(),
            usage_tags: "[\"PERSONALIZE\"]".to_string(),
            visibility: "OPEN".to_string(),
            behavior_rule: String::new(),
            source_kind: "AT_MENTION".to_string(),
            owner_type: "SPACE".to_string(),
            owner_key: "space:1".to_string(),
            subject_key: String::new(),
            audience: "CURRENT_SPACE".to_string(),
            source_conversation_key: "conv".to_string(),
            fact_key: "claim:v1:x".to_string(),
            policy_version: "v1".to_string(),
            occurrence_count: 2,
            source_kinds: "[\"AT_MENTION\"]".to_string(),
            source_message_ids: "[\"1\",\"2\"]".to_string(),
        };
        let owner = EffectiveOwner {
            owner_type: "SPACE".to_string(),
            owner_key: "space:1".to_string(),
            subject_key: String::new(),
            audience: "CURRENT_SPACE".to_string(),
            source_conversation_key: "conv".to_string(),
            fact_key: "claim:v1:x".to_string(),
            policy_version: "v1".to_string(),
        };
        assert_eq!(
            candidate_cas_digest("c-1", &candidate, &owner, "accepted", &"b".repeat(64),)
                .expect("candidate digest"),
            "7215ae62ec241daca6fe74cfa778fc00633685034207baf2620434c8b46d764d"
        );
    }

    fn request(path: &std::path::Path, candidate_id: &str) -> PromotionRequest {
        let conn = Connection::open(path).expect("open db for request CAS");
        let mut request = PromotionRequest {
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
            owner_type: String::new(),
            owner_key: String::new(),
            subject_key: String::new(),
            audience: String::new(),
            source_conversation_key: String::new(),
            fact_key: String::new(),
            policy_version: String::new(),
            cas_schema_version: 1,
            expected_scope_versions: BTreeMap::new(),
            expected_evidence_digest: String::new(),
            expected_candidate_digest: String::new(),
        };
        let candidate = load_candidate(&conn, &request)
            .expect("load candidate for CAS")
            .expect("candidate exists for CAS");
        let owner = effective_owner(&request, &candidate);
        let evidence: Vec<EvidenceDigestRow> = {
            let mut statement = conn
                .prepare(
                    "SELECT e.id, e.source_row_id, e.source_conversation_key, e.source_digest,
                            e.fact_subject_key, e.owner_key, e.audience, e.fact_key,
                            e.verification_status, e.provenance_json
                     FROM memory_evidence e
                     JOIN memory_claim_links l ON l.evidence_id = e.id
                     JOIN memory_claim_links s ON s.owner_key = e.owner_key
                       AND s.audience = e.audience AND s.entity_type = 'claim_state'
                       AND s.entity_id = e.fact_key AND s.claim_key = e.fact_key
                       AND s.projection_slot = 'eligibility' AND s.status = 'active'
                     WHERE e.candidate_id = ? AND e.owner_key = ? AND e.audience = ?
                       AND e.fact_key = ? AND e.verification_status = 'accepted'
                       AND l.entity_type = 'memory_candidate' AND l.entity_id = ?
                       AND l.claim_key = e.fact_key AND l.projection_slot = 'candidate'
                       AND l.status = 'active' ORDER BY e.id",
                )
                .expect("prepare evidence digest");
            statement
                .query_map(
                    (
                        candidate_id,
                        &owner.owner_key,
                        &owner.audience,
                        &owner.fact_key,
                        candidate_id,
                    ),
                    |row| {
                        let provenance: String = row.get(9)?;
                        let assessment_version = serde_json::from_str::<JsonValue>(&provenance)
                            .ok()
                            .and_then(|value| {
                                value
                                    .get("assessment_version")
                                    .and_then(JsonValue::as_str)
                                    .map(str::to_string)
                            })
                            .unwrap_or_default();
                        Ok(EvidenceDigestRow {
                            id: row.get(0)?,
                            source_row_id: row.get(1)?,
                            source_conversation_key: row.get(2)?,
                            source_digest: row.get(3)?,
                            fact_subject_key: row.get(4)?,
                            owner_key: row.get(5)?,
                            audience: row.get(6)?,
                            fact_key: row.get(7)?,
                            verification_status: row.get(8)?,
                            assessment_version,
                            provenance_json: provenance,
                        })
                    },
                )
                .expect("query evidence digest")
                .collect::<rusqlite::Result<Vec<_>>>()
                .expect("read evidence digest")
        };
        request.expected_evidence_digest = evidence_set_digest(&evidence).expect("evidence digest");
        for key in [owner.owner_key.as_str(), "global"] {
            let version = conn
                .query_row(
                    "SELECT COALESCE((SELECT version FROM memory_scope_versions WHERE scope_key = ?), 0)",
                    [key],
                    |row| row.get(0),
                )
                .expect("scope version");
            request
                .expected_scope_versions
                .insert(key.to_string(), version);
        }
        request.expected_candidate_digest = candidate_cas_digest(
            candidate_id,
            &candidate,
            &owner,
            "accepted",
            &request.expected_evidence_digest,
        )
        .expect("candidate digest");
        drop(conn);
        request
    }

    fn add_evidence(conn: &Connection, candidate_id: &str, row_id: i64, content: &str) {
        let fact_key = format!("preference.general:{row_id}");
        let conversation_key = format!("conversation-{row_id}");
        let snapshot = json!({
            "id": row_id,
            "group_id": "qq-group-1",
            "user_id": "1",
            "content": content,
            "source_kind": "AT_MENTION",
            "conversation_key": conversation_key,
            "bot_id": "bot-1"
        });
        let source_digest = snapshot_digest(&snapshot).expect("source digest");
        let provenance = json!({
            "assessment_version": "2026-10-08.1",
            "verification_status": "accepted",
            "claim_key": fact_key,
            "recording_author_key": "qq:1",
            "fact_object_key": "qq:1",
            "exact_support_span": content,
            "conversation_key": conversation_key,
            "source_id": row_id,
            "source_snapshot": snapshot
        });
        let evidence_id = format!("evidence-{row_id}");
        conn.execute(
            "INSERT INTO group_messages
             (id, group_id, user_id, content, source_kind, conversation_key, bot_id)
             VALUES (?, 'qq-group-1', '1', ?, 'AT_MENTION', ?, 'bot-1')",
            (row_id, content, &conversation_key),
        )
        .expect("source message");
        conn.execute(
            "UPDATE memory_candidates
             SET owner_type = 'SPACE', owner_key = 'space:space', subject_key = 'qq:1',
                 audience = 'CURRENT_SPACE', source_conversation_key = ?, fact_key = ?,
                 source_message_ids = ?
             WHERE id = ?",
            (
                &conversation_key,
                &fact_key,
                serde_json::to_string(&vec![row_id]).expect("source message ids"),
                candidate_id,
            ),
        )
        .expect("candidate provenance scope");
        conn.execute(
            "INSERT INTO memory_evidence (
                id, owner_type, owner_key, subject_key, audience, fact_key,
                source_conversation_key, source_row_id, candidate_id, fact_subject_key,
                source_digest, verification_status, provenance_json
             ) VALUES (?, 'SPACE', 'space:space', 'qq:1', 'CURRENT_SPACE', ?, ?, ?, ?,
                       'qq:1', ?, 'accepted', ?)",
            (
                &evidence_id,
                &fact_key,
                &conversation_key,
                row_id,
                candidate_id,
                &source_digest,
                provenance.to_string(),
            ),
        )
        .expect("accepted evidence");
        conn.execute(
            "INSERT INTO memory_claim_links (
                id, evidence_id, owner_key, audience, entity_type, entity_id, claim_key,
                projection_slot, projection_version, slot_digest, status
             ) VALUES (?, ?, 'space:space', 'CURRENT_SPACE', 'memory_candidate', ?, ?,
                       'candidate', 1, ?, 'active')",
            (
                format!("candidate-link-{row_id}"),
                &evidence_id,
                candidate_id,
                &fact_key,
                &source_digest,
            ),
        )
        .expect("candidate evidence link");
        conn.execute(
            "INSERT OR IGNORE INTO memory_claim_links (
                id, evidence_id, owner_key, audience, entity_type, entity_id, claim_key,
                projection_slot, projection_version, slot_digest, status
             ) VALUES (?, '', 'space:space', 'CURRENT_SPACE', 'claim_state', ?, ?,
                       'eligibility', 1, ?, 'active')",
            (
                format!("eligibility-link-{row_id}"),
                &fact_key,
                &fact_key,
                &source_digest,
            ),
        )
        .expect("active claim state");
    }

    fn setup() -> NamedTempFile {
        let file = NamedTempFile::new().expect("temp db");
        let conn = Connection::open(file.path()).expect("open db");
        conn.execute_batch(
            "CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER);
             INSERT INTO schema_meta (k, version) VALUES ('version', 19);
             CREATE TABLE memory_candidates (
               id TEXT PRIMARY KEY, group_shared_space TEXT, user_id TEXT, type TEXT,
               content TEXT, content_raw TEXT, importance REAL, confidence REAL,
               status TEXT, usage_tags TEXT, visibility TEXT, behavior_rule TEXT,
               source_kind TEXT, updated_at TEXT,
               owner_type TEXT DEFAULT 'SPACE', owner_key TEXT,
               subject_key TEXT DEFAULT '', audience TEXT DEFAULT 'CURRENT_SPACE',
               source_conversation_key TEXT DEFAULT '', fact_key TEXT DEFAULT '',
               policy_version TEXT DEFAULT '', occurrence_count INTEGER DEFAULT 1,
               source_kinds TEXT DEFAULT '[\"AT_MENTION\"]',
               source_message_ids TEXT DEFAULT '[]'
             );
             CREATE TABLE memories (
               id TEXT PRIMARY KEY, group_shared_space TEXT, user_id TEXT, type TEXT,
               content TEXT, content_raw TEXT, importance REAL, confidence REAL, status TEXT,
               confirmation_count INTEGER, last_confirmed_at TEXT, last_accessed_at TEXT,
               compressed_at TEXT, compression_version INTEGER, is_atomized INTEGER,
               usage_tags TEXT, visibility TEXT, trigger_data TEXT, behavior_rule TEXT,
               source_kind TEXT, updated_at TEXT,
               owner_type TEXT DEFAULT 'SPACE', owner_key TEXT,
               subject_key TEXT DEFAULT '', audience TEXT DEFAULT 'CURRENT_SPACE',
               source_conversation_key TEXT DEFAULT '', fact_key TEXT DEFAULT '',
               policy_version TEXT DEFAULT ''
             );
             CREATE TABLE group_messages (
               id INTEGER PRIMARY KEY, group_id TEXT, user_id TEXT, content TEXT,
               source_kind TEXT, conversation_key TEXT, bot_id TEXT
             );
             CREATE TABLE memory_evidence (
               id TEXT PRIMARY KEY, owner_type TEXT, owner_key TEXT, subject_key TEXT,
               audience TEXT, fact_key TEXT, source_conversation_key TEXT,
               source_row_id INTEGER, candidate_id TEXT, fact_subject_key TEXT,
               source_digest TEXT, verification_status TEXT, provenance_json TEXT
             );
             CREATE TABLE memory_claim_links (
               id TEXT PRIMARY KEY, evidence_id TEXT, owner_key TEXT, audience TEXT,
               entity_type TEXT, entity_id TEXT, claim_key TEXT, projection_slot TEXT,
               projection_version INTEGER, slot_digest TEXT, status TEXT,
               UNIQUE(evidence_id, entity_type, entity_id, claim_key, projection_slot)
             );
             CREATE TABLE memory_scope_versions (
               scope_key TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 1,
               updated_at TEXT DEFAULT CURRENT_TIMESTAMP
             );
             INSERT INTO memory_candidates
               (id, group_shared_space, user_id, type, content, content_raw, importance,
                confidence, status, usage_tags, visibility, behavior_rule, source_kind)
             VALUES ('c1', 'space', '1', 'PREFERENCE', '我喜欢羽毛球', '我喜欢羽毛球',
                     .8, .9, 'NEW', '[\"RECOMMEND\"]', 'OPEN', '', 'AT_MENTION');",
        )
        .expect("schema");
        add_evidence(&conn, "c1", 1, "我喜欢羽毛球");
        file
    }

    #[test]
    fn high_confidence_without_evidence_is_rejected() {
        let file = setup();
        let conn = Connection::open(file.path()).expect("open db");
        conn.execute("DELETE FROM memory_evidence", [])
            .expect("remove evidence");
        conn.execute("DELETE FROM memory_claim_links", [])
            .expect("remove links");
        drop(conn);
        let output = promote(request(file.path(), "c1")).expect("promotion gate");
        let conn = Connection::open(file.path()).expect("open db");
        let candidate_status: String = conn
            .query_row(
                "SELECT status FROM memory_candidates WHERE id = 'c1'",
                [],
                |row| row.get(0),
            )
            .expect("candidate status");
        let memories: i64 = conn
            .query_row("SELECT COUNT(*) FROM memories", [], |row| row.get(0))
            .expect("memory count");
        assert!(!output.promoted);
        assert_eq!(output.action, "accepted_evidence_missing");
        assert_eq!(candidate_status, "NEW");
        assert_eq!(memories, 0);
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
             VALUES ('c2', 'space', '1', 'PREFERENCE', '我喜欢羽毛球和游泳', '我喜欢羽毛球和游泳',
                     .9, .95, 'NEW', '[\"RECOMMEND\"]', 'OPEN', '', 'AT_MENTION')",
            [],
        )
        .expect("candidate");
        add_evidence(&conn, "c2", 2, "我喜欢羽毛球和游泳");
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
            "INSERT INTO memories
             (id, group_shared_space, user_id, type, content, content_raw, importance,
              confidence, status, confirmation_count, usage_tags, visibility)
             VALUES ('old', 'space', '1', 'PREFERENCE', '我不喜欢羽毛球', '我不喜欢羽毛球', .8, .95,
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
