- 返答は日本語で
- git stage, commitはユーザーが行うので、AI Agentは実行してはならない

## 開発コマンド

リポジトリルートの `dev.ps1`（`dev <command>` / `.\dev.ps1 <command>`）を推奨入口とする。
中身は既存手順（README / `scripts\check.ps1` / `make_build.bat`）を呼ぶだけの front-end。

- Setup: `dev setup`（`.venv` に requirements-dev.txt / requirements-build.txt を導入し `pre-commit install`）
- Install: `dev install`（`scripts\install-windows.ps1 -Build`。ビルドして Program Files へ配置。`-Destination <dir>` / `-NoBuild` 可）
- Build: `dev build`（`make_build.bat` → `dist\hiyoko-viewer\`）
- Run GUI: `dev gui`（`python main.py`。`dev run` も同じ）
- Test: `dev test`（`python -m pytest`、追加引数はそのまま pytest へ）
- Lint: `dev lint`（`ruff check .` + `ruff format --check .`）
- Full validation: `dev check`（`scripts\check.ps1`。`-SkipPreCommit` / `-CheckStaged` / `-Fix` を渡せる）
- Clean: `dev clean`（再生成可能な生成物のみ削除。`-DryRun` で確認のみ）

注意:
- `dev check` は `pre-commit run --all-files` を含み、自動修正でファイルを書き換えることがある。
- `dev install` は UAC 昇格を求め、既存のインストール先を置き換える。Agent はユーザーの指示なしに実行しないこと。
