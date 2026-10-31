param(
    [ValidateSet("Report", "Claim")]
    [string]$Mode = "Report",

    [string]$BaseUrl = "http://127.0.0.1:18086",

    [string]$DeviceId = "INSTITUTE-WINDOWS-DEMO-01",

    [switch]$SimulateCriticalDisk
)

$ErrorActionPreference = "Stop"

Write-Host "`nTECH SOLUTIONS - WINDOWS MONITORING AGENT" -ForegroundColor Cyan

# Ask for the agent token securely.
$secureToken = Read-Host "Enter AGENT_API_TOKEN" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)

try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $secureToken.Dispose()
}

$headers = @{
    Authorization = "Bearer $token"
}

function Send-AgentRequest {
    param(
        [string]$Path,
        [string]$Method = "GET",
        $Body = $null
    )

    $parameters = @{
        Uri = "$BaseUrl$Path"
        Method = $Method
        Headers = $headers
        TimeoutSec = 15
    }

    if ($null -ne $Body) {
        $parameters.ContentType = "application/json"
        $parameters.Body = $Body | ConvertTo-Json -Depth 8 -Compress
    }

    Invoke-RestMethod @parameters
}

function Get-DiskDiagnostics {
    $disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"

    $details = foreach ($disk in $disks) {
        $size = [double]$disk.Size
        $free = [double]$disk.FreeSpace

        $percent = if ($size -gt 0) {
            [math]::Round(($free / $size) * 100, 2)
        } else {
            0
        }

        "$($disk.DeviceID): Total=$([math]::Round($size / 1GB, 2))GB; Free=$([math]::Round($free / 1GB, 2))GB; FreePercent=$percent%"
    }

    return ($details -join "; ")
}

function Get-DiagnosticResult {
    param([string]$ActionType)

    switch ($ActionType) {
        "collect_disk_diagnostics" {
            return Get-DiskDiagnostics
        }

        "collect_memory_diagnostics" {
            $os = Get-CimInstance Win32_OperatingSystem

            $total = [double]$os.TotalVisibleMemorySize
            $free = [double]$os.FreePhysicalMemory
            $used = $total - $free
            $percent = if ($total -gt 0) {
                [math]::Round(($used / $total) * 100, 2)
            } else {
                0
            }

            return "Memory used: $([math]::Round($used / 1MB, 2))GB; Total: $([math]::Round($total / 1MB, 2))GB; Usage: $percent%"
        }

        "collect_process_diagnostics" {
            $processes = Get-Process |
                Sort-Object CPU -Descending |
                Select-Object -First 5

            $details = $processes | ForEach-Object {
                "$($_.ProcessName): PID=$($_.Id)"
            }

            return "Top processes: " + ($details -join "; ")
        }

        "collect_network_diagnostics" {
            $adapters = Get-NetAdapter -ErrorAction Stop

            $details = $adapters | ForEach-Object {
                "$($_.Name): Status=$($_.Status); LinkSpeed=$($_.LinkSpeed)"
            }

            return "Network adapters: " + ($details -join "; ")
        }

        default {
            throw "Unsupported diagnostic action: $ActionType"
        }
    }
}

if ($Mode -eq "Report") {

    Write-Host "`nCollecting Windows health metrics..."

    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$env:SystemDrive'"

    if (-not $disk -or $disk.Size -le 0) {
        throw "Unable to read system-drive information."
    }

    $actualDiskPercent = [math]::Round(
        ([double]$disk.FreeSpace / [double]$disk.Size) * 100, 2
    )

    $reportedDiskPercent = if ($SimulateCriticalDisk) {
        Write-Host "DEMO MODE: Reporting simulated 3% free disk space." -ForegroundColor Yellow
        3
    } else {
        $actualDiskPercent
    }

    $os = Get-CimInstance Win32_OperatingSystem
    $memoryPercent = [math]::Round(
        (1 - ([double]$os.FreePhysicalMemory / [double]$os.TotalVisibleMemorySize)) * 100,
        2
    )

    $cpuValues = Get-CimInstance Win32_Processor |
        Measure-Object -Property LoadPercentage -Average

    $cpuPercent = [double]$cpuValues.Average

    $networkConnected = @(
        Get-NetAdapter -ErrorAction SilentlyContinue |
        Where-Object Status -eq "Up"
    ).Count -gt 0

    $payload = @{
        device_id = $DeviceId
        hostname = $env:COMPUTERNAME
        metrics = @{
            disk_free_percent = $reportedDiskPercent
            cpu_percent = $cpuPercent
            memory_percent = $memoryPercent
            network_connected = $networkConnected
        }
    }

    $response = Send-AgentRequest `
        -Path "/api/agent/health" `
        -Method POST `
        -Body $payload

    Write-Host "`nHealth report submitted successfully." -ForegroundColor Green
    $response | ConvertTo-Json -Depth 8

    Write-Host "`nActual system-drive free space: $actualDiskPercent%"

    if ($SimulateCriticalDisk) {
        Write-Host "NOTE: The reported 3% alert was simulated; actual disk usage was not modified." -ForegroundColor Yellow
    }
}

if ($Mode -eq "Claim") {

    Write-Host "`nChecking for approved diagnostic tasks..."

    $claim = Send-AgentRequest `
        -Path "/api/agent/tasks/claim" `
        -Method POST `
        -Body @{ device_id = $DeviceId }

    if (-not $claim.tasks -or $claim.tasks.Count -eq 0) {
        Write-Host "No approved tasks are available."
        exit 0
    }

    foreach ($task in $claim.tasks) {

        Write-Host "`nReceived task $($task.task_id)"
        Write-Host "Action: $($task.action_type)"

        $result = "completed"

        try {
            $note = Get-DiagnosticResult -ActionType $task.action_type

            $note = "Read-only Windows diagnostics on $env:COMPUTERNAME. $note. No files or settings modified."

        } catch {
            $result = "failed"
            $note = "Diagnostic failed: $($_.Exception.Message)"
        }

        if ($note.Length -gt 950) {
            $note = $note.Substring(0, 950)
        }

        $report = @{
            device_id = $DeviceId
            result = $result
            note = $note
        }

        $resultResponse = Send-AgentRequest `
            -Path "/api/agent/tasks/$($task.task_id)/result" `
            -Method POST `
            -Body $report

        Write-Host "`nExecution result:" -ForegroundColor Cyan
        $resultResponse | ConvertTo-Json -Depth 5
    }
}
