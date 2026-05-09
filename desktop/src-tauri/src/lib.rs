// NotebookAI Tauri 2 desktop shell
//
// Spawns the FastAPI backend as a sidecar, waits for /healthz to return 200,
// then reveals the main window. Prefers the bundled PyInstaller binary
// (registered as a Tauri sidecar via tauri.conf.json's `bundle.externalBin`).
// Falls back to `uv run notebookai-api` for the developer loop when no
// bundled binary is present.

use std::env;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Emitter, Manager, RunEvent, WindowEvent};
use tauri_plugin_shell::process::{Command, CommandChild};
use tauri_plugin_shell::ShellExt;

#[cfg(target_os = "macos")]
use tauri::utils::config::WindowEffectsConfig;
#[cfg(target_os = "macos")]
use tauri::utils::{WindowEffect, WindowEffectState};

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 8765;
const SIDECAR_NAME: &str = "notebookai-api";

struct BackendChild(Mutex<Option<CommandChild>>);

#[tauri::command]
fn backend_url() -> String {
    format!("http://{}:{}", BACKEND_HOST, BACKEND_PORT)
}

/// Build the env-var list every backend invocation needs.
///
/// We always pin host/port so the Rust shell and the Python process agree on
/// the URL the webview will hit. ANTHROPIC_API_KEY is forwarded only when the
/// user has it set in their shell — the wiki-only-mode path handles absence.
fn backend_env() -> Vec<(String, String)> {
    let mut env_vars = vec![
        ("NOTEBOOKAI_API_HOST".to_string(), BACKEND_HOST.to_string()),
        ("NOTEBOOKAI_API_PORT".to_string(), BACKEND_PORT.to_string()),
    ];
    if let Ok(key) = env::var("ANTHROPIC_API_KEY") {
        if !key.is_empty() {
            env_vars.push(("ANTHROPIC_API_KEY".to_string(), key));
        }
    }
    env_vars
}

/// Absolute path to the backend project directory, baked at compile time.
///
/// Resolves `desktop/src-tauri/../../backend`. Using `env!("CARGO_MANIFEST_DIR")`
/// keeps the path correct regardless of where the binary is launched from
/// (dev runs `cwd` is variable; packaged `.app` launches with `cwd=/`).
const BACKEND_PROJECT_DIR: &str =
    concat!(env!("CARGO_MANIFEST_DIR"), "/../../backend");

/// Try the bundled PyInstaller sidecar first; if it isn't on disk (typical
/// in `pnpm tauri:dev` before anyone has run `python desktop/sidecar/build.py`),
/// fall back to `uv run`. The fallback keeps the developer loop unchanged.
fn build_backend_command(app: &tauri::AppHandle) -> Result<Command, String> {
    let shell = app.shell();
    let env_vars = backend_env();

    match shell.sidecar(SIDECAR_NAME) {
        Ok(cmd) => {
            let cmd = cmd.envs(env_vars);
            Ok(cmd)
        }
        Err(err) => {
            eprintln!(
                "[notebookai] bundled sidecar '{}' not found ({}); \
                 falling back to `uv run --project {} notebookai-api`. \
                 This is expected during development. To bundle for release, run \
                 `python desktop/sidecar/build.py`.",
                SIDECAR_NAME, err, BACKEND_PROJECT_DIR
            );
            let cmd = shell
                .command("uv")
                .args([
                    "run",
                    "--project",
                    BACKEND_PROJECT_DIR,
                    "notebookai-api",
                ])
                .envs(env_vars);
            Ok(cmd)
        }
    }
}

fn spawn_backend(app: &tauri::AppHandle) -> Result<CommandChild, String> {
    let cmd = build_backend_command(app)?;

    let (mut rx, child) = cmd
        .spawn()
        .map_err(|e| format!("failed to spawn backend sidecar: {e}"))?;

    // Drain stdout/stderr so the child does not block on a full pipe.
    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        use tauri_plugin_shell::process::CommandEvent;
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let _ = app_handle.emit(
                        "backend-log",
                        serde_json::json!({"stream": "stdout", "line": String::from_utf8_lossy(&line)}),
                    );
                }
                CommandEvent::Stderr(line) => {
                    let _ = app_handle.emit(
                        "backend-log",
                        serde_json::json!({"stream": "stderr", "line": String::from_utf8_lossy(&line)}),
                    );
                }
                CommandEvent::Terminated(payload) => {
                    let _ = app_handle.emit("backend-terminated", payload.code);
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(child)
}

async fn wait_for_health(timeout: Duration) -> bool {
    let url = format!("http://{}:{}/healthz", BACKEND_HOST, BACKEND_PORT);
    let deadline = std::time::Instant::now() + timeout;

    while std::time::Instant::now() < deadline {
        // Minimal HTTP probe via std::net so we avoid pulling in reqwest just for this.
        if let Ok(mut stream) = std::net::TcpStream::connect((BACKEND_HOST, BACKEND_PORT)) {
            use std::io::{Read, Write};
            let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
            let req = format!("GET /healthz HTTP/1.0\r\nHost: {}\r\n\r\n", BACKEND_HOST);
            if stream.write_all(req.as_bytes()).is_ok() {
                let mut buf = [0u8; 64];
                if let Ok(n) = stream.read(&mut buf) {
                    if n > 12 && buf[9] == b'2' {
                        let _ = url; // keep variable used for clarity
                        return true;
                    }
                }
            }
        }
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
    false
}

#[cfg(target_os = "macos")]
fn apply_vibrancy(window: &tauri::WebviewWindow) {
    let effects = WindowEffectsConfig {
        effects: vec![WindowEffect::Sidebar],
        state: Some(WindowEffectState::Active),
        radius: None,
        color: None,
    };
    if let Err(e) = window.set_effects(effects) {
        eprintln!("set_effects failed: {e}");
    }
}

#[cfg(not(target_os = "macos"))]
fn apply_vibrancy(_window: &tauri::WebviewWindow) {
    // Linux/Windows: rely on transparent + frontend backdrop. Wayland transparency is best-effort.
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .manage(BackendChild(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![backend_url])
        .setup(|app| {
            let handle = app.handle().clone();

            // Spawn the backend sidecar; surface failure via event but keep the UI alive.
            match spawn_backend(&handle) {
                Ok(child) => {
                    let state = handle.state::<BackendChild>();
                    *state.0.lock().unwrap() = Some(child);
                }
                Err(err) => {
                    eprintln!("backend sidecar failed to start: {err}");
                    let _ = handle.emit("backend-error", err);
                }
            }

            // Apply vibrancy and reveal the window once /healthz responds.
            tauri::async_runtime::spawn(async move {
                let healthy = wait_for_health(Duration::from_secs(30)).await;
                if let Some(window) = handle.get_webview_window("main") {
                    apply_vibrancy(&window);
                    let _ = window.show();
                    let _ = window.set_focus();
                }
                let _ = handle.emit("notebookai-ready", healthy);
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // macOS UX: hide instead of quit on close so the dock icon keeps the app alive.
            #[cfg(target_os = "macos")]
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    let _ = window.hide();
                    api.prevent_close();
                }
            }
            #[cfg(not(target_os = "macos"))]
            {
                let _ = window;
                let _ = event;
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<BackendChild>() {
                    if let Some(child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
