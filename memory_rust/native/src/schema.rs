use rusqlite::Connection;

pub const BACKEND_API_VERSION: u32 = 2;
// v16（多人身份修复计划 §6.2/§6.3）：信封列与身份声明表不在 native 读写面，
// 但合同按整库版本精确匹配——Python 侧 memory_rust/backend.py 同步。
pub const MEMORY_SCHEMA_VERSION: i64 = 16;

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
