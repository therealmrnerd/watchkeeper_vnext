#NoEnv
#SingleInstance Force
#Persistent
SetTitleMatchMode, 2

global RepoRoot := _ResolveRepoRoot()
global RunStackScript := RepoRoot . "\scripts\run_stack.ps1"
global PsExe := _ResolvePowerShell()
global ActionBusy := false
global LastActionMs := 0

if (!FileExist(RunStackScript)) {
    MsgBox, 16, Watchkeeper Stack Tray, Could not find run_stack.ps1 at:`n%RunStackScript%
    ExitApp
}

Menu, Tray, NoStandard
Menu, Tray, Add, Start Stack, MenuStart
Menu, Tray, Add, Stop Stack, MenuStop
Menu, Tray, Add, Restart Stack, MenuRestart
Menu, Tray, Add
Menu, Tray, Add, Status (Open Console), MenuStatus
Menu, Tray, Add, Open Logs Folder, MenuOpenLogs
Menu, Tray, Add
Menu, Tray, Add, Exit, MenuExit
Menu, Tray, Default, Status (Open Console)
Menu, Tray, Tip, Watchkeeper Stack Control
Menu, Tray, Click, 2
return

MenuStart:
    _RunStackAction("start")
return

MenuStop:
    _RunStackAction("stop")
return

MenuRestart:
    _RunStackAction("restart")
return

MenuStatus:
    _OpenStatusConsole()
return

MenuOpenLogs:
    logsPath := RepoRoot . "\logs"
    if (!FileExist(logsPath)) {
        FileCreateDir, %logsPath%
    }
    Run, explorer.exe "%logsPath%"
return

MenuExit:
    ExitApp
return

_ResolveRepoRoot() {
    scriptDir := A_ScriptDir
    SplitPath, scriptDir, , parentDir
    return parentDir
}

_ResolvePowerShell() {
    ps7 := A_ProgramFiles . "\PowerShell\7\pwsh.exe"
    if (FileExist(ps7)) {
        return ps7
    }
    return "powershell.exe"
}

_RunStackAction(action) {
    global RepoRoot, RunStackScript, PsExe, ActionBusy, LastActionMs
    now := A_TickCount
    if (ActionBusy) {
        TrayTip, Watchkeeper Stack, Stack action already running. Please wait., 2, 17
        return
    }
    if ((now - LastActionMs) < 1200) {
        return
    }
    ActionBusy := true
    LastActionMs := now
    cmd := Chr(34) . PsExe . Chr(34)
        . " -NoProfile -ExecutionPolicy Bypass -File "
        . Chr(34) . RunStackScript . Chr(34)
        . " -Action " . action

    RunWait, %cmd%, %RepoRoot%, Hide UseErrorLevel
    ActionBusy := false
    if (ErrorLevel) {
        TrayTip, Watchkeeper Stack, % "Action '" . action . "' failed (exit " . ErrorLevel . "). Check logs\\*.err.log.", 6, 17
        return
    }
    TrayTip, Watchkeeper Stack, % "Action '" . action . "' complete.", 3, 1
}

_OpenStatusConsole() {
    global RepoRoot, RunStackScript, PsExe
    cmd := Chr(34) . PsExe . Chr(34)
        . " -NoExit -ExecutionPolicy Bypass -File "
        . Chr(34) . RunStackScript . Chr(34)
        . " -Action status"
    Run, %cmd%, %RepoRoot%
}
