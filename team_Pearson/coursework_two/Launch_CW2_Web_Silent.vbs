Option Explicit

Dim shell, fso, scriptDir, pythonExe, host, port, url, dbPort, dbContainer, launchCmd, i
Dim dockerDesktop
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
host = "127.0.0.1"
port = "8011"
url = "http://" & host & ":" & port & "/"
dbPort = "5439"
dbContainer = "postgres_db_cw"
dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"

pythonExe = ResolvePython(scriptDir)
If pythonExe = "" Then
  MsgBox "CW2 Web could not find a usable Python interpreter.", vbCritical, "CW2 Web"
  WScript.Quit 1
End If

If Not EnsurePostgresReady(dbPort, dbContainer) Then
  MsgBox "CW2 Web could not reach PostgreSQL on port " & dbPort & ".", vbExclamation, "CW2 Web"
  WScript.Quit 1
End If

' Stop any previous listener so the newest code is always loaded.
shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""$conn = Get-NetTCPConnection -LocalPort " & port & " -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }""", 0, True
WScript.Sleep 1000

launchCmd = "cmd /c cd /d """ & scriptDir & """ && """ & pythonExe & """ -m uvicorn api.main:app --host " & host & " --port " & port
shell.Run launchCmd, 0, False

For i = 1 To 20
  WScript.Sleep 1000
  If IsServerReady(url & "health") Then
    shell.Run url, 1, False
    WScript.Quit 0
  End If
Next

MsgBox "CW2 Web server did not become ready in time. Please try again.", vbExclamation, "CW2 Web"
WScript.Quit 1

Function ResolvePython(baseDir)
  Dim candidates, idx
  candidates = Array( _
    "C:\Users\grace\miniconda3\python.exe", _
    fso.BuildPath(fso.GetParentFolderName(baseDir), "coursework_one\.venv\Scripts\python.exe") _
  )

  For idx = 0 To UBound(candidates)
    If fso.FileExists(candidates(idx)) Then
      ResolvePython = candidates(idx)
      Exit Function
    End If
  Next

  ResolvePython = ""
End Function

Function EnsurePostgresReady(targetPort, containerName)
  Dim attempt
  If Not EnsureDockerReady() Then
    EnsurePostgresReady = False
    Exit Function
  End If

  If IsTcpPortOpen(targetPort) Then
    EnsurePostgresReady = True
    Exit Function
  End If

  shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""docker start " & containerName & " *> $null""", 0, True

  For attempt = 1 To 25
    WScript.Sleep 1000
    If IsTcpPortOpen(targetPort) Then
      EnsurePostgresReady = True
      Exit Function
    End If
  Next

  EnsurePostgresReady = False
End Function

Function EnsureDockerReady()
  Dim attempt
  If IsDockerReady() Then
    EnsureDockerReady = True
    Exit Function
  End If

  shell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""Start-Service -Name 'com.docker.service' -ErrorAction SilentlyContinue""", 0, True

  If fso.FileExists(dockerDesktop) Then
    shell.Run """" & dockerDesktop & """", 0, False
  End If

  For attempt = 1 To 45
    WScript.Sleep 2000
    If IsDockerReady() Then
      EnsureDockerReady = True
      Exit Function
    End If
  Next

  EnsureDockerReady = False
End Function

Function IsDockerReady()
  Dim exitCode
  exitCode = shell.Run( _
    "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""docker version *> $null; if ($LASTEXITCODE -eq 0) { exit 0 } else { exit 1 }""", _
    0, _
    True _
  )
  IsDockerReady = (exitCode = 0)
End Function

Function IsTcpPortOpen(targetPort)
  Dim exitCode
  exitCode = shell.Run( _
    "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ""$ok = Test-NetConnection -ComputerName 127.0.0.1 -Port " & targetPort & " -WarningAction SilentlyContinue; if ($ok.TcpTestSucceeded) { exit 0 } else { exit 1 }""", _
    0, _
    True _
  )
  IsTcpPortOpen = (exitCode = 0)
End Function

Function IsServerReady(checkUrl)
  Dim http
  On Error Resume Next
  Set http = CreateObject("MSXML2.XMLHTTP")
  http.Open "GET", checkUrl, False
  http.Send
  IsServerReady = (Err.Number = 0 And http.Status = 200)
  On Error GoTo 0
End Function
