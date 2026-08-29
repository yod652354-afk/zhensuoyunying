# RevOS 一键启动（后端 8001 + 前端 5173）
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:TMP = Join-Path $root '.tmp'; $env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null

Write-Host "应用数据库迁移 (Alembic)..." -ForegroundColor Green
$py = Join-Path $root 'backend\.venv\Scripts\python.exe'
Push-Location (Join-Path $root 'backend')
# 兼容两类库：已由 create_all 创建但无 alembic 记录的旧库（先 stamp 初始版本再升级）
& $py -m alembic upgrade head 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "首次迁移失败，尝试 stamp 初始版本后重试（兼容 create_all 旧库）..." -ForegroundColor Yellow
  & $py -c "from alembic.config import Config; from alembic import command; command.stamp(Config('alembic.ini'), 'a715f4a894bb')" 2>$null
  & $py -m alembic upgrade head 2>$null
}
Pop-Location

Write-Host "启动后端 (8001)..." -ForegroundColor Green
$bk = Start-Process -FilePath (Join-Path $root 'backend\.venv\Scripts\python.exe') `
  -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8001' `
  -WorkingDirectory (Join-Path $root 'backend') -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 8

Write-Host "启动前端 (5173)..." -ForegroundColor Green
$fe = Start-Process -FilePath 'node' `
  -ArgumentList (Join-Path $root 'frontend\node_modules\vite\bin\vite.js') `
  -WorkingDirectory (Join-Path $root 'frontend') -PassThru -WindowStyle Hidden

Write-Host ""
Write-Host "RevOS 后端 API 文档 : http://127.0.0.1:8001/docs" -ForegroundColor Cyan
Write-Host "RevOS 前端运营后台 : http://localhost:5173" -ForegroundColor Cyan
Write-Host "停止: 任务管理器结束 uvicorn/vite 进程，或执行: Stop-Process -Id $($bk.Id),$($fe.Id)" -ForegroundColor Yellow