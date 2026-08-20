mod commands;
mod python;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            commands::run_doctor,
            commands::get_status,
            commands::start_bot,
            commands::stop_bot,
            commands::read_log_tail,
            commands::get_config,
            commands::save_config,
            commands::list_models,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
