# 開発用の統一コマンド入口。既存の正式手順（README / scripts/check.ps1 / make_build.bat）を
# 呼び出すだけの薄い front-end で、処理そのものはここで再実装しない。
#
#   .\dev.ps1 <command> [args...]      (cmd.exe からは dev <command>)
#
# 追加の引数はそのまま下位コマンドへ渡す（例: .\dev.ps1 test -k apng / .\dev.ps1 check -SkipPreCommit）。

$ErrorActionPreference = "Stop"

$RepoRoot = $PSScriptRoot
$VenvScripts = Join-Path $RepoRoot ".venv\Scripts"

$Command = if ($args.Count -gt 0) { [string]$args[0] } else { "help" }
# if 式の出力は単一要素だと配列が展開されてしまうので、外側の @() で必ず配列にする。
$Rest = @(if ($args.Count -gt 1) { $args[1..($args.Count - 1)] })

# scripts/check.ps1 と同じ規則: repo の .venv があればそれを使い、無ければ PATH の python。
function Get-Python {
    $venvPython = Join-Path $VenvScripts "python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return $venvPython
    }
    return "python"
}

# ネイティブコマンドを実行し、失敗したら終了コードを保持したまま中断する。
function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [scriptblock]$Block
    )

    Write-Host "==> $Name"
    & $Block
    if ($LASTEXITCODE -ne 0) {
        $script:ExitCode = $LASTEXITCODE
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

function Show-Help {
    Write-Host @"
Usage: dev <command> [args...]   (repo root から .\dev.ps1 <command> でも可)

Commands:
  install   ビルドして Program Files へインストール (scripts\install-windows.ps1 -Build)
            [-Destination <dir>] [-NoBuild: 既存の dist\hiyoko-viewer をそのまま入れる]
  setup     開発用依存を .venv に導入 (requirements-dev.txt / requirements-build.txt, pre-commit install)
  build     PyInstaller ビルド (make_build.bat -> dist\hiyoko-viewer\)
  gui       GUI アプリを起動 (python main.py [画像パス])
  run       gui と同じ (このアプリには CLI モードが無いため)
  test      テスト実行 (python -m pytest [pytest args])
  lint      ruff check . と ruff format --check .
  check     commit 前の正式チェック (scripts\check.ps1 [-SkipPreCommit] [-CheckStaged] [-Fix])
  clean     再生成可能な生成物のみ削除 (-DryRun で削除対象の表示のみ)
  help      このヘルプを表示

Notes:
  check は pre-commit run --all-files を含み、自動修正でファイルが書き換わることがある。
  install はコピー時に管理者昇格 (UAC) を求め、既存のインストール先を置き換える。
"@
}

# .venv\Scripts を PATH の先頭に足した状態で実行する（終了後に元へ戻す）。
# make_build.bat は PATH 上の pyinstaller を呼ぶので、venv 未 activate でも動くようにするため。
function Invoke-WithVenvPath {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Block
    )

    $savedPath = $env:PATH
    try {
        if (Test-Path -LiteralPath $VenvScripts) {
            $env:PATH = "$VenvScripts;$savedPath"
        }
        & $Block
    } finally {
        $env:PATH = $savedPath
    }
}

# dev に渡された残り引数を、下位スクリプトの param 定義に沿ったハッシュテーブル splat に変換する。
# 配列 splat では "-Name" が文字列扱いになるうえ、下位スクリプトは未知の引数を黙って無視するため。
function ConvertTo-ScriptSplat {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Script,

        [Parameter(Mandatory = $true)]
        [string]$Label,

        [object[]]$Arguments = @()
    )

    $params = @{}
    foreach ($p in $Script.Ast.ParamBlock.Parameters) {
        $params[$p.Name.VariablePath.UserPath] = ($p.StaticType -eq [switch])
    }
    $available = ($params.Keys | Sort-Object | ForEach-Object { "-$_" }) -join " "

    $splat = @{}
    for ($i = 0; $i -lt $Arguments.Count; $i++) {
        $arg = [string]$Arguments[$i]
        if (-not (($arg -match '^-(\w+)$') -and $params.ContainsKey($Matches[1]))) {
            $script:ExitCode = 2
            throw "Unknown $Label option: $arg (available: $available)"
        }
        $name = $Matches[1]
        if ($params[$name]) {
            $splat[$name] = $true
        } elseif ($i + 1 -lt $Arguments.Count) {
            $i++
            $splat[$name] = $Arguments[$i]
        } else {
            $script:ExitCode = 2
            throw "$Label option -$name requires a value"
        }
    }
    return $splat
}

# BOM 無し UTF-8 の既存スクリプトも Windows PowerShell 5.1 で読めるよう UTF-8 として読み込む。
function Get-ScriptBlockFromFile([string]$Path) {
    return [scriptblock]::Create([System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8))
}

function Invoke-Install {
    # ビルド付きインストールは scripts\install-windows.ps1 -Build に委譲する。
    # -NoBuild だけは dev 側で解釈し、それ以外 (-Destination 等) はそのまま渡す。
    $installPath = Join-Path $RepoRoot "scripts\install-windows.ps1"
    $noBuild = $Rest -contains "-NoBuild"
    $forward = @($Rest | Where-Object { [string]$_ -ne "-NoBuild" })
    $splat = ConvertTo-ScriptSplat -Script (Get-ScriptBlockFromFile $installPath) -Label "install" -Arguments $forward
    if (-not $noBuild) {
        $splat["Build"] = $true
    }

    Invoke-WithVenvPath {
        # 未昇格時は昇格プロセスの終了コードで exit するので、それを拾えるよう事前にリセットする。
        $global:LASTEXITCODE = 0
        & $installPath @splat
        if ($LASTEXITCODE -ne 0) {
            $script:ExitCode = $LASTEXITCODE
            throw "install-windows.ps1 failed with exit code $LASTEXITCODE"
        }
    }
}

function Invoke-Setup {
    $venvPython = Join-Path $VenvScripts "python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Invoke-Native "python -m venv .venv" { & python -m venv (Join-Path $RepoRoot ".venv") }
    }
    Invoke-Native "pip install -r requirements-dev.txt" {
        & $venvPython -m pip install -r (Join-Path $RepoRoot "requirements-dev.txt")
    }
    Invoke-Native "pip install -r requirements-build.txt" {
        & $venvPython -m pip install -r (Join-Path $RepoRoot "requirements-build.txt")
    }
    Invoke-Native "pre-commit install" { & $venvPython -m pre_commit install }
}

function Invoke-Build {
    Invoke-WithVenvPath {
        Invoke-Native "make_build.bat" { & cmd /c (Join-Path $RepoRoot "make_build.bat") }
    }
}

function Invoke-Gui {
    $python = Get-Python
    Invoke-Native "python main.py $Rest" { & $python (Join-Path $RepoRoot "main.py") @Rest }
}

function Invoke-Test {
    $python = Get-Python
    Invoke-Native "pytest $Rest" { & $python -m pytest @Rest }
}

function Invoke-Lint {
    $python = Get-Python
    Invoke-Native "ruff check ." { & $python -m ruff check . }
    Invoke-Native "ruff format --check ." { & $python -m ruff format --check . }
}

function Invoke-Check {
    # 正式なチェックは scripts\check.ps1 に集約されているので、そのまま委譲する。
    $checkPath = Join-Path $RepoRoot "scripts\check.ps1"
    # check.ps1 は BOM 無し UTF-8 なので、5.1 ではファイル直接ではなく UTF-8 で読んだ scriptblock を実行する。
    $checkBlock = Get-ScriptBlockFromFile $checkPath
    $switches = ConvertTo-ScriptSplat -Script $checkBlock -Label "check" -Arguments $Rest

    if ($PSVersionTable.PSVersion.Major -ge 6) {
        & $checkPath @switches
    } else {
        & $checkBlock @switches
    }
}

function Invoke-Clean {
    $dryRun = $Rest -contains "-DryRun"

    # .gitignore 済みで、ツールが再生成するものだけを対象にする。
    # dist\*.zip（配布物）や tmp\ 直下の手作業ファイル、.venv は対象外。
    $targets = @(
        "build",
        "dist\hiyoko-viewer",
        ".pytest_cache",
        ".ruff_cache",
        "tmp\ruff-cache",
        "tmp\.coverage",
        ".coverage",
        "coverage.xml",
        "htmlcov"
    ) | ForEach-Object { Join-Path $RepoRoot $_ }

    $targets += @(Get-ChildItem -LiteralPath $RepoRoot -File -Force |
        Where-Object { $_.Name -like ".coverage.*" } |
        ForEach-Object { $_.FullName })
    foreach ($dir in @("src", "tests", "scripts")) {
        $base = Join-Path $RepoRoot $dir
        if (Test-Path -LiteralPath $base) {
            $targets += @(Get-ChildItem -LiteralPath $base -Recurse -Directory -Force |
                Where-Object { $_.Name -eq "__pycache__" -or $_.Name -like "*.egg-info" } |
                ForEach-Object { $_.FullName })
        }
    }

    foreach ($target in $targets) {
        if (-not (Test-Path -LiteralPath $target)) {
            continue
        }
        # 念のため git 管理下のファイルを含むものは消さない。
        $tracked = & git -C $RepoRoot ls-files -- $target
        if ($tracked) {
            Write-Host "skip (tracked): $target"
            continue
        }
        if ($dryRun) {
            Write-Host "would remove: $target"
        } else {
            Write-Host "remove: $target"
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }
}

$script:ExitCode = 0
Push-Location $RepoRoot
try {
    switch ($Command) {
        "help" { Show-Help }
        "install" { Invoke-Install }
        "setup" { Invoke-Setup }
        "build" { Invoke-Build }
        "gui" { Invoke-Gui }
        "run" { Invoke-Gui }
        "test" { Invoke-Test }
        "lint" { Invoke-Lint }
        "check" { Invoke-Check }
        "clean" { Invoke-Clean }
        default {
            Write-Host "Unknown command: $Command" -ForegroundColor Red
            Show-Help
            $script:ExitCode = 2
        }
    }
} catch {
    Write-Host $_ -ForegroundColor Red
    if ($script:ExitCode -eq 0) {
        $script:ExitCode = 1
    }
} finally {
    Pop-Location
}
exit $script:ExitCode
