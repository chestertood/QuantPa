' Double-click this once to turn QuantPa into a normal desktop program:
' a Desktop icon and a Start menu entry that launch it with one click.
'
' The shortcuts store an absolute path, so run this again after moving or
' renaming the folder. Uninstalling is deleting the shortcuts.
Set sh = CreateObject("WScript.Shell")
base = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\"

MakeShortcut sh.SpecialFolders("Desktop") & "\QuantPa.lnk", "start.bat"
MakeShortcut sh.SpecialFolders("Programs") & "\QuantPa.lnk", "start.bat"
MakeShortcut sh.SpecialFolders("Programs") & "\QuantPa (Stop).lnk", "stop.bat"

' Popup, not MsgBox: it closes itself after 10s instead of waiting forever.
sh.Popup "QuantPa is on your Desktop and in the Start menu." & vbCrLf & _
         "Stop it from Start menu > QuantPa (Stop).", 10, "QuantPa", 64

Sub MakeShortcut(path, target)
  Set lnk = sh.CreateShortcut(path)
  lnk.TargetPath = base & target
  lnk.WorkingDirectory = base
  lnk.IconLocation = base & "quantpa-v3.ico"
  lnk.WindowStyle = 7   ' minimised — the build window shouldn't grab the screen
  lnk.Description = "QuantPa"
  lnk.Save
End Sub
