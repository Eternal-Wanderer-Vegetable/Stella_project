use rusqlite::Connection;

pub const BACKEND_API_VERSION: u32 = 3;
// v19 promotion 在 native IMMEDIATE 事务内核 accepted lineage、来源 digest 与
// scope epoch CAS；旧扩展必须因整库版本不匹配而拒绝读写。
// v20 是 FTS 分词重灌迁移（Python migrate_v20）：native 不做 FTS，但本门禁按
// 库的 schema_meta.version 严格相等放行，Python 侧 SQLite schema 升级必须同步
// 抬本合同号并重编译（见 memory_rust/backend.py MEMORY_SCHEMA_VERSION）。
pub const MEMORY_SCHEMA_VERSION: i64 = 20;

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
