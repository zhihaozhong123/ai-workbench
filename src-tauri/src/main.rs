// 入口：直接调用 lib 中的 run()
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    ai_workbench_lib::run()
}
