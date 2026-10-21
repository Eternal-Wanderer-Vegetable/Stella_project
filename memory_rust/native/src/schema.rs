use rusqlite::Connection;

pub const BACKEND_API_VERSION: u32 = 4;
// v19 promotion 在 native IMMEDIATE 事务内核 accepted lineage、来源 digest 与
// scope epoch CAS；旧扩展必须因整库版本不匹配而拒绝读写。
// v20 是 FTS 分词重灌迁移（Python migrate_v20）：native 不做 FTS，但本门禁按
// 库的 schema_meta.version 严格相等放行，Python 侧 SQLite schema 升级必须同步
// 抬本合同号并重编译（见 memory_rust/backend.py MEMORY_SCHEMA_VERSION）。
// v21 增加 opaque platform_message_id / subject_key；旧扩展不得读新库。
pub const MEMORY_SCHEMA_VERSION: i64 = 21;

pub fn ensure_supported(conn: &Connection) -> Result<(), String> {
    let table_exists = conn
        .query_row(
            "SELECT EXISTS(
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'schema_meta'
            )",
            [],
            |row| row.get::<_, i64>(0),
        )
        .map_err(|err| format!("schema probe failed: {err}"))?;

    if table_exists == 0 {
        return Err("schema_meta table is missing; run the Python migration first".to_string());
    }

    let version = conn
        .query_row(
            "SELECT version FROM schema_meta WHERE k = 'version'",
            [],
            |row| row.get::<_, i64>(0),
        )
        .map_err(|err| format!("schema version probe failed: {err}"))?;

    if version != MEMORY_SCHEMA_VERSION {
        return Err(format!(
            "unsupported memory schema: expected {MEMORY_SCHEMA_VERSION}, got {version}"
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{ensure_supported, MEMORY_SCHEMA_VERSION};
    use rusqlite::Connection;

    #[test]
    fn accepts_only_the_current_schema_version() {
        let conn = Connection::open_in_memory().expect("open");
        conn.execute_batch(
            "CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER);
             INSERT INTO schema_meta (k, version) VALUES ('version', 21);",
        )
        .expect("schema");
        assert_eq!(MEMORY_SCHEMA_VERSION, 21);
        assert!(ensure_supported(&conn).is_ok());
    }

    #[test]
    fn rejects_the_previous_schema_version() {
        let conn = Connection::open_in_memory().expect("open");
        conn.execute_batch(
            "CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER);
             INSERT INTO schema_meta (k, version) VALUES ('version', 20);",
        )
        .expect("schema");
        assert!(ensure_supported(&conn)
            .unwrap_err()
            .contains("expected 21, got 20"));
    }
}
