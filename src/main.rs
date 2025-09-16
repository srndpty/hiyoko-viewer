// src/main.rs

// eframe::run_native を呼び出すために必要な型をインポートします
use eframe;
use eframe::egui;

fn main() -> Result<(), eframe::Error> {
    let native_options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([640.0, 480.0])
            .with_min_inner_size([300.0, 220.0]),
        ..Default::default()
    };

    eframe::run_native(
        "My Image Viewer",
        native_options,
        Box::new(|_cc| {
            // アプリケーションの状態を作成します。
            // v0.32では、このクロージャはResultを返す必要があります。
            // 成功した場合は Ok(Box::new(...)) を返します。
            Ok(Box::new(MyApp::default()))
        }),
    )
}

// アプリケーションの状態を保持する構造体
struct MyApp {}

// MyAppのデフォルト値を設定
impl Default for MyApp {
    fn default() -> Self {
        Self {}
    }
}

// eframe::App トレイトを実装します
impl eframe::App for MyApp {
    // この update メソッドが毎フレーム呼び出されて、UIを描画します。
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("Hello, world!");
            ui.label("最新版のeframeで動作するコードです！");
        });
    }
}