' Runs a command with no console window at all — used by start.bat so the two
' servers don't leave stray cmd windows on the taskbar.
'
' `start /min` only minimises; the windows stay in the taskbar and closing one
' by accident kills a server. WScript.Shell.Run with a window style of 0 hides
' it outright.
'
' Output still has to go somewhere: a hidden process with nowhere to write is a
' crash you never see. Everything is appended to a log file instead.
'
' Args: 0 = working directory, 1 = command line, 2 = log file
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = WScript.Arguments(0)

q = Chr(34)  ' a literal " — nesting quotes inside a VBS string is unreadable
cmd = "cmd /c " & WScript.Arguments(1) & " >> " & q & WScript.Arguments(2) & q & " 2>&1"

' 0 = hidden window, False = don't wait for it to exit
sh.Run cmd, 0, False
