# Opdaterer Task Scheduler-opgaven "Debatstof-scraper" til ny projektmappe
$TaskName   = "Debatstof-scraper"
$NyBatSti   = 'C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus\Jyllands-Posten\Progs\debat scraber\Start scraper.bat'
$NyArbjDir  = 'C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus\Jyllands-Posten\Progs\debat scraber'

$Opgave = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $Opgave) {
    Write-Host "FEJL: Fandt ikke Task Scheduler-opgaven '$TaskName'." -ForegroundColor Red
    exit 1
}

$Action = New-ScheduledTaskAction `
    -Execute  'cmd.exe' `
    -Argument "/c `"$NyBatSti`"" `
    -WorkingDirectory $NyArbjDir

Set-ScheduledTask -TaskName $TaskName -Action $Action | Out-Null

Write-Host "OK: '$TaskName' er opdateret til:" -ForegroundColor Green
Write-Host "    $NyBatSti"
