rem ビルド設定は hiyoko-viewer.spec に集約する（JXL fallback 用の hidden import を含む）。
pyinstaller --noconfirm hiyoko-viewer.spec
