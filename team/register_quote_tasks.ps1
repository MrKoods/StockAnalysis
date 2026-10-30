# Registers the Quote Clerk's two scheduled tasks (run once, by the user, in PowerShell).
# Mon-Fri 06:31 PT (9:31 AM ET, after the open) and 12:56 PT (3:56 PM ET, before the close), plain local time.
$team = "C:\Users\user\Documents\Git\StockAnalysis-Team"
$py = "C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe"
foreach ($t in @(@{n = "StockAnalysis_Team_QuoteOpen"; w = "open"; at = "06:31"},
                 @{n = "StockAnalysis_Team_QuoteClose"; w = "close"; at = "12:56"})) {
    $arg = "-NoProfile -WindowStyle Hidden -Command `"& '$py' '$team\tools\quotes.py' capture $($t.w) *>> '$team\state\logs\quote_task.log'`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory "$team\tools"
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $t.at
    $trigger.StartBoundary = "2026-11-02T$($t.at):00"      # no UTC offset -> follows the clock through DST
    $settings = New-ScheduledTaskSettingsSet -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $t.n -Action $action -Trigger $trigger -Settings $settings `
        -Description "Team Quote Clerk: Webull bid/ask at the $($t.w)" -Force | Out-Null
}
Get-ScheduledTask StockAnalysis_Team_Quote* | ForEach-Object {
    "{0}  next run {1}" -f $_.TaskName, ($_ | Get-ScheduledTaskInfo).NextRunTime }
