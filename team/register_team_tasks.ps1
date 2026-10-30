# Registers the team's three operating tasks (run once, by the user, in PowerShell):
#   StockAnalysis_Team_QuoteOpen   Mon-Fri 06:31 PT (9:31 AM ET)  Quote Clerk, bid/ask after the open
#   StockAnalysis_Team_QuoteClose  Mon-Fri 12:56 PT (3:56 PM ET)  Quote Clerk, bid/ask before the close
#   StockAnalysis_Team_ScanOps     Mon-Sat every 10 min 05:00-18:50  Scan Operator: verify / re-run / alert
# All on plain local time (no UTC offset) so they follow the clock through daylight-saving changes.
$team = "C:\Users\user\Documents\Git\StockAnalysis-Team"
$py = "C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe"

function Register-Team($name, $file, $scriptArgs, $days, $at, $desc, $repeatMinutes) {
    $log = "$team\state\logs\" + ($(if ($file -eq "quotes.py") { "quote_task.log" } else { "scan_ops_task.log" }))
    $arg = "-NoProfile -WindowStyle Hidden -Command `"& '$py' '$team\tools\$file' $scriptArgs *>> '$log'`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory "$team\tools"
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $at
    $trigger.StartBoundary = "2026-11-02T$($at):00"
    if ($repeatMinutes) {
        $rep = New-ScheduledTaskTrigger -Once -At $at -RepetitionInterval (New-TimeSpan -Minutes $repeatMinutes) `
               -RepetitionDuration (New-TimeSpan -Hours 13 -Minutes 55)
        $trigger.Repetition = $rep.Repetition
    }
    $settings = New-ScheduledTaskSettingsSet -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Description $desc -Force | Out-Null
}

$weekdays = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
Register-Team "StockAnalysis_Team_QuoteOpen"  "quotes.py" "capture open"  $weekdays "06:31" "Team Quote Clerk: Webull bid/ask after the open" $null
Register-Team "StockAnalysis_Team_QuoteClose" "quotes.py" "capture close" $weekdays "12:56" "Team Quote Clerk: Webull bid/ask before the close" $null
Register-Team "StockAnalysis_Team_ScanOps"    "scan_ops.py" "" ($weekdays + "Saturday") "05:00" "Team Scan Operator: verify, re-run, alert" 10

Get-ScheduledTask StockAnalysis_Team_* | ForEach-Object {
    "{0,-32} next run {1}" -f $_.TaskName, ($_ | Get-ScheduledTaskInfo).NextRunTime }
