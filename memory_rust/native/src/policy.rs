use std::collections::{BTreeMap, HashMap, HashSet};

use chrono::{DateTime, NaiveDateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::similarity::is_similar;

pub const MODE_CASUAL_REPLY: &str = "CASUAL_REPLY";
pub const MODE_ACTIVE_JOIN: &str = "ACTIVE_JOIN";
pub const MODE_HUMOR: &str = "HUMOR";
pub const MODE_TECH_HELP: &str = "TECH_HELP";
pub const MODE_RECOMMEND: &str = "RECOMMEND";
pub const MODE_EMOTIONAL: &str = "EMOTIONAL";
pub const MODE_CONFLICT_AVOID: &str = "CONFLICT_AVOID";
pub const MODE_GROUP_EVENT: &str = "GROUP_EVENT";

const CONTEXTUAL_MIN_SIMILARITY: f64 = 0.05;
const EMBEDDING_CONTEXTUAL_MIN: f64 = 0.25;
const SCORE_MIN: f64 = 0.40;
const TYPE_MISMATCH_PENALTY: f64 = 0.75;
const W_CONTEXT: f64 = 0.25;
const W_USAGE: f64 = 0.20;
const W_SEMANTIC: f64 = 0.35;
const W_RECENCY: f64 = 0.10;
const W_CONFIDENCE: f64 = 0.05;
const W_IMPORTANCE: f64 = 0.05;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MemoryRecord {
    pub id: String,
    pub group_shared_space: String,
    pub user_id: Option<String>,
    #[serde(rename = "type")]
    pub memory_type: String,
    pub content: String,
    pub importance: Option<f64>,
    pub confidence: Option<f64>,
    pub visibility: String,
    pub usage_tags: Vec<String>,
    pub trigger_data: Option<String>,
    pub behavior_rule: Option<String>,
    pub last_accessed_at: Option<String>,
    pub last_confirmed_at: Option<String>,
    #[serde(rename = "_score", default)]
    pub score: Option<f64>,
    #[serde(rename = "_score_parts", default)]
    pub score_parts: BTreeMap<String, f64>,
}

impl MemoryRecord {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        id: String,
        group_shared_space: String,
        user_id: Option<String>,
        memory_type: String,
        content: String,
        importance: Option<f64>,
        confidence: Option<f64>,
        visibility: String,
        usage_tags: Vec<String>,
        trigger_data: Option<String>,
        behavior_rule: Option<String>,
        last_accessed_at: Option<String>,
        last_confirmed_at: Option<String>,
    ) -> Self {
        Self {
            id,
            group_shared_space,
            user_id,
            memory_type,
            content,
            importance,
            confidence,
            visibility,
            usage_tags,
            trigger_data,
            behavior_rule,
            last_accessed_at,
            last_confirmed_at,
            score: None,
            score_parts: BTreeMap::new(),
        }
    }
}

pub fn normalize_mode(mode: &str) -> &'static str {
    match mode.trim().to_uppercase().as_str() {
        MODE_ACTIVE_JOIN => MODE_ACTIVE_JOIN,
        MODE_HUMOR => MODE_HUMOR,
        MODE_TECH_HELP => MODE_TECH_HELP,
        MODE_RECOMMEND => MODE_RECOMMEND,
        MODE_EMOTIONAL => MODE_EMOTIONAL,
        MODE_CONFLICT_AVOID => MODE_CONFLICT_AVOID,
        MODE_GROUP_EVENT => MODE_GROUP_EVENT,
        _ => MODE_CASUAL_REPLY,
    }
}

fn usage_matrix(mode: &str) -> &'static [(&'static str, f64)] {
    match mode {
        MODE_ACTIVE_JOIN => &[
            ("TOPIC_START", 5.0),
            ("TOPIC_CONTINUE", 5.0),
            ("GROUP_CONTEXT", 5.0),
            ("HUMOR", 4.0),
            ("RELATION_CONTEXT", 3.0),
        ],
        MODE_HUMOR => &[
            ("HUMOR", 5.0),
            ("RELATION_CONTEXT", 5.0),
            ("GROUP_CONTEXT", 5.0),
            ("TOPIC_CONTINUE", 4.0),
        ],
        MODE_TECH_HELP => &[
            ("ANSWER_CONTEXT", 5.0),
            ("PERSONALIZE", 5.0),
            ("TOPIC_CONTINUE", 3.0),
            ("TOPIC_START", 3.0),
        ],
        MODE_RECOMMEND => &[
            ("RECOMMEND", 5.0),
            ("PERSONALIZE", 4.0),
            ("ANSWER_CONTEXT", 3.0),
            ("TOPIC_CONTINUE", 2.0),
        ],
        MODE_EMOTIONAL => &[
            ("EMOTIONAL_SUPPORT", 5.0),
            ("PERSONALIZE", 5.0),
            ("RELATION_CONTEXT", 3.0),
            ("TOPIC_CONTINUE", 3.0),
        ],
        MODE_CONFLICT_AVOID => &[
            ("BOUNDARY_PROTECTION", 5.0),
            ("CONFLICT_AVOID", 5.0),
            ("RELATION_CONTEXT", 4.0),
        ],
        MODE_GROUP_EVENT => &[
            ("GROUP_CONTEXT", 5.0),
            ("TOPIC_CONTINUE", 4.0),
            ("RELATION_CONTEXT", 4.0),
            ("TOPIC_START", 3.0),
        ],
        _ => &[
            ("PERSONALIZE", 5.0),
            ("TOPIC_CONTINUE", 5.0),
            ("RELATION_CONTEXT", 3.0),
            ("TOPIC_START", 3.0),
            ("EMOTIONAL_SUPPORT", 3.0),
            ("HUMOR", 2.0),
        ],
    }
}

fn forbidden(mode: &str, tag: &str) -> bool {
    match mode {
        MODE_CASUAL_REPLY | MODE_HUMOR | MODE_RECOMMEND | MODE_GROUP_EVENT => {
            matches!(tag, "BOUNDARY_PROTECTION" | "CONFLICT_AVOID")
        }
        MODE_ACTIVE_JOIN => matches!(
            tag,
            "BOUNDARY_PROTECTION" | "CONFLICT_AVOID" | "EMOTIONAL_SUPPORT"
        ),
        MODE_TECH_HELP => matches!(tag, "HUMOR" | "BOUNDARY_PROTECTION"),
        MODE_EMOTIONAL => matches!(tag, "HUMOR" | "RECOMMEND"),
        MODE_CONFLICT_AVOID => matches!(tag, "TOPIC_START" | "HUMOR"),
        _ => false,
    }
}

fn compatible_types(tag: &str) -> &'static [&'static str] {
    match tag {
        "TOPIC_START" => &["GROUP_CONTEXT", "PREFERENCE", "EVENT"],
        "TOPIC_CONTINUE" => &["EVENT", "GROUP_CONTEXT", "PLAN", "PREFERENCE"],
        "ANSWER_CONTEXT" => &["FACT", "EVENT", "PLAN"],
        "RECOMMEND" => &["PREFERENCE", "FACT", "EVENT"],
        "PERSONALIZE" => &["STYLE", "PREFERENCE"],
        "RELATION_CONTEXT" => &["RELATION", "EVENT"],
        "HUMOR" => &["RELATION", "GROUP_CONTEXT", "EVENT", "STYLE"],
        "GROUP_CONTEXT" => &["GROUP_CONTEXT", "EVENT", "RELATION"],
        "EMOTIONAL_SUPPORT" => &["EVENT", "RELATION", "STYLE"],
        "BOUNDARY_PROTECTION" => &["PREFERENCE", "RELATION"],
        "CONFLICT_AVOID" => &["RELATION", "EVENT", "PREFERENCE"],
        _ => &[],
    }
}

pub fn usage_allowed(mode: &str, memory: &MemoryRecord) -> (bool, f64) {
    let mode = normalize_mode(mode);
    if memory.usage_tags.is_empty() {
        return (true, 1.0);
    }
    let allowed = usage_matrix(mode);
    let mut best: f64 = 0.0;
    let mut allowed_any = false;
    for tag in &memory.usage_tags {
        if forbidden(mode, tag) {
            continue;
        }
        let Some((_, raw_score)) = allowed.iter().find(|(candidate, _)| *candidate == tag) else {
            continue;
        };
        allowed_any = true;
        let score = if compatible_types(tag).contains(&memory.memory_type.as_str()) {
            *raw_score
        } else {
            *raw_score * TYPE_MISMATCH_PENALTY
        };
        best = best.max(score);
    }
    (allowed_any, best)
}

pub fn visibility_allowed(mode: &str, visibility: &str) -> bool {
    let mode = normalize_mode(mode);
    let visibility = visibility.to_uppercase();
    match mode {
        MODE_CONFLICT_AVOID => visibility != "INTERNAL",
        _ => !matches!(visibility.as_str(), "RESTRICTED" | "INTERNAL"),
    }
}

fn parse_trigger_data(raw: &Option<String>) -> Option<Value> {
    raw.as_deref()
        .and_then(|value| serde_json::from_str(value).ok())
}

fn trigger_topic_match(query: &str, memory: &MemoryRecord) -> bool {
    let Some(Value::Object(data)) = parse_trigger_data(&memory.trigger_data) else {
        return false;
    };
    let query = query.to_lowercase();
    if data
        .get("keywords")
        .and_then(Value::as_array)
        .is_some_and(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .any(|keyword| !keyword.is_empty() && query.contains(&keyword.to_lowercase()))
        })
    {
        return true;
    }
    let synonyms: HashMap<&str, &[&str]> = HashMap::from([
        ("game", &["游戏", "game", "玩", "开黑", "联机", "steam"][..]),
        (
            "tech",
            &[
                "代码", "报错", "显存", "显卡", "cuda", "gpu", "部署", "模型",
            ][..],
        ),
        (
            "emotion",
            &["累", "压力", "难过", "心情", "焦虑", "哭", "烦"][..],
        ),
        (
            "boundary",
            &["碰", "摸", "别碰", "边界", "冒犯", "玩笑"][..],
        ),
        (
            "event",
            &["活动", "聚会", "比赛", "报名", "开黑", "团建"][..],
        ),
        ("group", &["群", "群友", "大家", "群里"][..]),
    ]);
    data.get("topics")
        .and_then(Value::as_array)
        .is_some_and(|topics| {
            topics.iter().filter_map(Value::as_str).any(|topic| {
                synonyms
                    .get(topic.to_lowercase().as_str())
                    .is_some_and(|words| words.iter().any(|word| query.contains(word)))
            })
        })
}

fn tokenize(value: &str) -> HashSet<String> {
    let mut tokens = HashSet::new();
    let chars: Vec<char> = value.to_lowercase().chars().collect();
    for (index, ch) in chars.iter().enumerate() {
        if ch.is_ascii_alphanumeric() || *ch == '_' {
            let mut word = String::new();
            for candidate in chars[index..].iter() {
                if candidate.is_ascii_alphanumeric() || *candidate == '_' {
                    word.push(*candidate);
                } else {
                    break;
                }
            }
            if !word.is_empty() {
                tokens.insert(word);
            }
        } else if ('\u{4e00}'..='\u{9fff}').contains(ch) {
            for size in [2usize, 3usize] {
                if index + size <= chars.len() {
                    let gram: String = chars[index..index + size].iter().collect();
                    if gram.chars().all(|c| ('\u{4e00}'..='\u{9fff}').contains(&c)) {
                        tokens.insert(gram);
                    }
                }
            }
        }
    }
    tokens
}

fn semantic_similarity(query: &str, content: &str) -> f64 {
    if query.is_empty() || content.is_empty() {
        return 0.0;
    }
    let query_tokens = tokenize(query);
    let content_tokens = tokenize(content);
    if query_tokens.is_empty() || content_tokens.is_empty() {
        return 0.0;
    }
    let intersection = query_tokens.intersection(&content_tokens).count() as f64;
    let union = query_tokens.union(&content_tokens).count() as f64;
    let hits = query_tokens
        .iter()
        .filter(|token| content.to_lowercase().contains(token.as_str()))
        .count() as f64;
    (intersection / union + hits * 0.1).min(1.0)
}

fn parse_timestamp(value: &Option<String>) -> Option<i64> {
    let value = value.as_deref()?;
    if let Ok(parsed) = DateTime::parse_from_rfc3339(value) {
        return Some(parsed.timestamp());
    }
    NaiveDateTime::parse_from_str(value, "%Y-%m-%d %H:%M:%S")
        .ok()
        .map(|parsed| parsed.and_utc().timestamp())
}

fn timestamp(memory: &MemoryRecord) -> i64 {
    parse_timestamp(&memory.last_confirmed_at)
        .or_else(|| parse_timestamp(&memory.last_accessed_at))
        .unwrap_or_else(|| Utc::now().timestamp())
}

fn mode_limit(mode: &str) -> usize {
    match normalize_mode(mode) {
        MODE_TECH_HELP | MODE_RECOMMEND | MODE_GROUP_EVENT => 5,
        MODE_CONFLICT_AVOID => 10,
        _ => 3,
    }
}

pub fn rank_memories(
    memories: &[MemoryRecord],
    mode: &str,
    query: &str,
    semantic_scores: &HashMap<String, f64>,
) -> Vec<MemoryRecord> {
    let mode = normalize_mode(mode);
    let embedding_path = !semantic_scores.is_empty();
    let (w_ctx, w_usg, w_sem, w_rec, w_conf, w_imp) = if embedding_path {
        (
            W_CONTEXT,
            W_USAGE,
            W_SEMANTIC,
            W_RECENCY,
            W_CONFIDENCE,
            W_IMPORTANCE,
        )
    } else {
        let base = W_CONTEXT + W_USAGE + W_RECENCY + W_CONFIDENCE + W_IMPORTANCE;
        let scale = 1.0 / base;
        (
            W_CONTEXT * scale,
            W_USAGE * scale,
            0.0,
            W_RECENCY * scale,
            W_CONFIDENCE * scale,
            W_IMPORTANCE * scale,
        )
    };
    let reference = memories
        .iter()
        .map(timestamp)
        .max()
        .unwrap_or_else(|| Utc::now().timestamp());
    let reference = reference.min(Utc::now().timestamp());
    let contextual_min = if embedding_path {
        EMBEDDING_CONTEXTUAL_MIN
    } else {
        CONTEXTUAL_MIN_SIMILARITY
    };

    let mut ranked = Vec::new();
    for memory in memories {
        let (allowed, usage_score) = usage_allowed(mode, memory);
        if !allowed || !visibility_allowed(mode, &memory.visibility) {
            continue;
        }
        let semantic = semantic_scores
            .get(&memory.id)
            .copied()
            .unwrap_or_else(|| semantic_similarity(query, &memory.content))
            .clamp(0.0, 1.0);
        if memory.visibility.eq_ignore_ascii_case("CONTEXTUAL")
            && usage_score < 5.0
            && !trigger_topic_match(query, memory)
            && semantic < contextual_min
        {
            continue;
        }
        let age_days = ((reference - timestamp(memory)).max(0) as f64) / 86_400.0;
        let recency = (-age_days / 30.0).exp().clamp(0.0, 1.0);
        let context_match = if trigger_topic_match(query, memory) {
            1.0
        } else {
            (usage_score / 5.0).min(1.0)
        };
        let confidence = memory.confidence.unwrap_or(0.7).clamp(0.0, 1.0);
        let importance = memory.importance.unwrap_or(0.5).clamp(0.0, 1.0);
        let parts = BTreeMap::from([
            ("ctx".to_string(), w_ctx * context_match),
            ("usg".to_string(), w_usg * usage_score / 5.0),
            ("sem".to_string(), w_sem * semantic),
            ("rec".to_string(), w_rec * recency),
            ("conf".to_string(), w_conf * confidence),
            ("imp".to_string(), w_imp * importance),
        ]);
        let score = parts.values().sum::<f64>();
        let mut memory = memory.clone();
        memory.score = Some((score * 10_000.0).round() / 10_000.0);
        memory.score_parts = parts
            .into_iter()
            .map(|(key, value)| (key, (value * 1_000.0).round() / 1_000.0))
            .collect();
        ranked.push(memory);
    }
    ranked.sort_by(|left, right| {
        right
            .score
            .unwrap_or_default()
            .total_cmp(&left.score.unwrap_or_default())
            .then_with(|| left.id.cmp(&right.id))
    });
    ranked
}

pub fn merge_similar(memories: &[MemoryRecord]) -> Vec<MemoryRecord> {
    let mut merged = Vec::new();
    for memory in memories {
        let target = merged.iter_mut().find(|existing: &&mut MemoryRecord| {
            existing.memory_type == memory.memory_type
                && existing.user_id == memory.user_id
                && is_similar(&existing.content, &memory.content)
        });
        if let Some(existing) = target {
            existing.content = crate::similarity::merge_content(&existing.content, &memory.content);
            existing.confidence = Some(
                existing
                    .confidence
                    .unwrap_or(0.0)
                    .max(memory.confidence.unwrap_or(0.0)),
            );
            existing.importance = Some(
                existing
                    .importance
                    .unwrap_or(0.0)
                    .max(memory.importance.unwrap_or(0.0)),
            );
        } else {
            merged.push(memory.clone());
        }
    }
    merged
}

pub fn split_behavior_constraints(
    memories: &[MemoryRecord],
) -> (Vec<MemoryRecord>, Vec<MemoryRecord>) {
    let mut behavior = Vec::new();
    let mut conversation = Vec::new();
    for memory in memories {
        if matches!(
            memory.visibility.to_uppercase().as_str(),
            "RESTRICTED" | "INTERNAL"
        ) || memory
            .usage_tags
            .iter()
            .any(|tag| matches!(tag.as_str(), "BOUNDARY_PROTECTION" | "CONFLICT_AVOID"))
        {
            behavior.push(memory.clone());
        } else {
            conversation.push(memory.clone());
        }
    }
    (conversation, behavior)
}

pub fn apply_conversation_limit(
    memories: &[MemoryRecord],
    mode: &str,
) -> (Vec<MemoryRecord>, HashSet<String>) {
    let limit = mode_limit(mode);
    let mut threshold_ids = HashSet::new();
    let conversation = memories
        .iter()
        .filter(|memory| {
            if memory.score.unwrap_or_default() < SCORE_MIN {
                threshold_ids.insert(memory.id.clone());
                false
            } else {
                true
            }
        })
        .take(limit)
        .cloned()
        .collect();
    (conversation, threshold_ids)
}

#[cfg(test)]
mod tests {
    use super::{merge_similar, rank_memories, MemoryRecord, MODE_RECOMMEND};
    use std::collections::HashMap;

    fn memory(id: &str, content: &str, tags: &[&str]) -> MemoryRecord {
        MemoryRecord::new(
            id.to_string(),
            "space".to_string(),
            Some("1".to_string()),
            "PREFERENCE".to_string(),
            content.to_string(),
            Some(0.8),
            Some(0.9),
            "OPEN".to_string(),
            tags.iter().map(|tag| (*tag).to_string()).collect(),
            None,
            None,
            Some("2026-09-01 00:00:00".to_string()),
            None,
        )
    }

    #[test]
    fn policy_filters_and_orders_recommendations() {
        let memories = vec![
            memory("blocked", "用户喜欢写代码", &["HUMOR"]),
            memory("allowed", "用户不喜欢恐怖题材", &["RECOMMEND"]),
        ];
        let ranked = rank_memories(&memories, MODE_RECOMMEND, "推荐游戏", &HashMap::new());
        assert_eq!(
            ranked
                .iter()
                .map(|item| item.id.as_str())
                .collect::<Vec<_>>(),
            vec!["allowed"]
        );
    }

    #[test]
    fn similarity_merge_preserves_user_scope() {
        let mut other_user = memory("other", "用户喜欢游戏", &["RECOMMEND"]);
        other_user.user_id = Some("2".to_string());
        let merged = merge_similar(&[memory("one", "用户喜欢游戏", &["RECOMMEND"]), other_user]);
        assert_eq!(merged.len(), 2);
    }
}
