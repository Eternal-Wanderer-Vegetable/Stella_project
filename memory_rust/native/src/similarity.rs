use std::collections::HashSet;

const SIMILARITY_THRESHOLD: f64 = 0.65;

pub fn normalize_text(value: &str) -> String {
    let mut output = String::new();
    let mut pending_space = false;
    for ch in value.trim().to_lowercase().chars() {
        if ch.is_alphanumeric() || ('\u{4e00}'..='\u{9fff}').contains(&ch) {
            if pending_space && !output.is_empty() {
                output.push(' ');
            }
            pending_space = false;
            output.push(ch);
        } else {
            pending_space = true;
        }
    }
    output
}

fn word_set(value: &str) -> HashSet<String> {
    normalize_text(value)
        .split_whitespace()
        .map(str::to_string)
        .collect()
}

fn jaccard(a: &HashSet<String>, b: &HashSet<String>) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let intersection = a.intersection(b).count() as f64;
    let union = a.union(b).count() as f64;
    intersection / union
}

pub fn is_similar(a: &str, b: &str) -> bool {
    if a.trim().is_empty() || b.trim().is_empty() {
        return false;
    }
    let a_norm = normalize_text(a);
    let b_norm = normalize_text(b);
    if a_norm.is_empty() || b_norm.is_empty() {
        return false;
    }
    a_norm.contains(&b_norm)
        || b_norm.contains(&a_norm)
        || jaccard(&word_set(&a_norm), &word_set(&b_norm)) >= SIMILARITY_THRESHOLD
}

/// 归一化后完全一致（引号/标点/大小写/空白差异忽略）；空值返回 false。
/// 供「跨类型仍可合并」判定使用：类型词表对称呼类内容两可，同一事实两次
/// 抽取可能得到不同 type，归一化逐字相同的跨类型重复合并仍是安全的。
pub fn same_normalized_text(a: &str, b: &str) -> bool {
    if a.trim().is_empty() || b.trim().is_empty() {
        return false;
    }
    normalize_text(a) == normalize_text(b)
}

pub fn merge_content(old: &str, new: &str) -> String {
    let old = old.trim();
    let new = new.trim();
    if old.is_empty() {
        return new.to_string();
    }
    if new.is_empty() {
        return old.to_string();
    }
    // 引号/标点变体（如 “X” 与 「X」）归一化后同文，但互不为原始子串——
    // 落到分号拼接会把同一事实在一条记忆里写两遍，必须在这里拦截。
    if same_normalized_text(old, new) {
        return if old.len() >= new.len() {
            old.to_string()
        } else {
            new.to_string()
        };
    }
    if old.contains(new) {
        return old.to_string();
    }
    if new.contains(old) {
        return new.to_string();
    }
    format!("{old}；{new}")
}

#[cfg(test)]
mod tests {
    use super::{is_similar, merge_content, same_normalized_text};

    #[test]
    fn similar_text_merges_containment_and_jaccard() {
        assert!(is_similar("喜欢本地 AI", "用户喜欢本地 AI 模型"));
        assert!(is_similar("喜欢 python 和 rust", "喜欢 python 和 rust"));
        assert!(!is_similar("喜欢咖啡", "讨厌下雨"));
    }

    #[test]
    fn normalized_equal_ignores_quote_variants() {
        assert!(same_normalized_text(
            "希望被称呼为“歌姬吧”",
            "希望被称呼为「歌姬吧」"
        ));
        assert!(!same_normalized_text("喜欢咖啡", "喜欢喝茶"));
        assert!(!same_normalized_text("有内容", ""));
    }

    #[test]
    fn merge_keeps_the_more_complete_text() {
        assert_eq!(
            merge_content("喜欢游戏", "用户喜欢游戏和音乐"),
            "用户喜欢游戏和音乐"
        );
        assert_eq!(merge_content("喜欢咖啡", "也喜欢茶"), "喜欢咖啡；也喜欢茶");
    }

    #[test]
    fn merge_does_not_duplicate_normalized_equal_variants() {
        assert_eq!(
            merge_content("希望被称呼为“歌姬吧”", "希望被称呼为「歌姬吧」"),
            "希望被称呼为“歌姬吧”"
        );
    }
}
