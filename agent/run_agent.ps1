# Launches the unattended review agent (Claude Code, headless) and posts its summary to Discord.
#   powershell -NoProfile -ExecutionPolicy Bypass -File run_agent.ps1 -Mode daily
#   powershell -NoProfile -ExecutionPolicy Bypass -File run_agent.ps1 -Mode weekly
# Scheduled by StockAnalysis_Agent_DailyReview / StockAnalysis_Agent_WeeklyResearch. See agent/README.md.
param([ValidateSet('daily', 'weekly')][string]$Mode = 'daily')

$ErrorActionPreference = 'Continue'
$Live = 'C:\Users\user\Documents\Git\StockAnalysis'
$V3 = 'C:\Users\user\Documents\Git\StockAnalysis-V3'
$Work = 'C:\Users\user\Documents\Git\StockAnalysis-agent'
$Today = Get-Date -Format 'yyyy-MM-dd'
$LogDir = Join-Path $Work 'agent\logs'
New-Item -ItemType Directory -Force $LogDir, (Join-Path $Work 'agent\state') | Out-Null
$Log = Join-Path $LogDir "$Today-$Mode.log"
$Discord = Join-Path $Work 'agent\reports\discord.txt'

function Post-Discord([string]$Text) {
    $line = Select-String -Path (Join-Path $Live '.env') -Pattern '^\s*DISCORD_WEBHOOK_URL\s*=\s*(.+)$' | Select-Object -First 1
    if (-not $line) { "no DISCORD_WEBHOOK_URL in .env" | Out-File -FilePath $Log -Append -Encoding utf8; return }
    $url = $line.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
    if ($Text.Length -gt 1900) { $Text = $Text.Substring(0, 1900) + '...' }
    $body = @{ username = 'StockAnalysis - Review Agent'; content = $Text } | ConvertTo-Json -Compress
    try { Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) | Out-Null }
    catch { "Discord post failed: $_" | Out-File -FilePath $Log -Append -Encoding utf8 }
}

"=== $Mode run started $(Get-Date -Format s) ===" | Out-File -FilePath $Log -Encoding utf8

# 1. Bring the agent branch up to date with the live branch. Proposed fixes on `agent` are replayed
#    on top; a conflict leaves the branch as it was and is reported instead of guessed at.
Push-Location $Work
git rebase Version-1 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { git rebase --abort 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8; $RebaseNote = 'agent branch could NOT be rebased onto Version-1 (conflict) - working on the previous base' }
else { $RebaseNote = 'agent branch rebased onto Version-1 cleanly' }

# 2. Context the agent can't gather itself (it has no PowerShell access).
$tasks = Get-ScheduledTask -TaskName 'StockAnalysis_*' | ForEach-Object {
    $i = $_ | Get-ScheduledTaskInfo
    '{0,-40} last {1:yyyy-MM-dd HH:mm}  result {2,-11} next {3:yyyy-MM-dd HH:mm}' -f $_.TaskName, $i.LastRunTime, $i.LastTaskResult, $i.NextRunTime
}
@("Run mode: $Mode", "Today (Pacific): $Today $(Get-Date -Format 'HH:mm')", $RebaseNote, '',
  'Scheduled tasks (LastTaskResult 0 = success; 267011 = never run; 2147946720 = missed while asleep):') + $tasks +
  @('', 'Live V2 branch, last commits:') + (git -C $Live log --oneline -5) +
  @('', 'Live V3 branch, last commits:') + (git -C $V3 log --oneline -3) |
  Set-Content (Join-Path $Work 'agent\state\context.txt') -Encoding utf8

# 3. Run Claude headless. dontAsk = anything not allowed in agent_settings.json is refused, never prompted.
$prompt = "Today is $Today. Run the $Mode routine: read agent/prompts/common.md, then agent/prompts/" +
          $(if ($Mode -eq 'daily') { 'daily_review.md' } else { 'weekly_research.md' }) + ' and follow it exactly.'
$start = Get-Date
& claude -p $prompt --permission-mode dontAsk --settings (Join-Path $Work 'agent\agent_settings.json') `
    --add-dir $Live $V3 -n "agent-$Mode-$Today" 2>&1 | Out-File -FilePath $Log -Append -Encoding utf8
$code = $LASTEXITCODE
Pop-Location
"=== claude exited $code at $(Get-Date -Format s) ===" | Out-File -FilePath $Log -Append -Encoding utf8

# 4. Post the agent's own summary if it wrote one this run; otherwise say it failed.
if ((Test-Path $Discord) -and ((Get-Item $Discord).LastWriteTime -gt $start)) {
    Post-Discord (Get-Content $Discord -Raw -Encoding utf8)
} else {
    $tail = (Get-Content $Log -Tail 8) -join "`n"
    Post-Discord ("[FAILED] Review agent ($Mode, $Today) did not finish - no report written (exit $code). Log: $Log`n" + $tail)
}
