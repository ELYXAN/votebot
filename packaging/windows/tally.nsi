; NSIS-Installer für Tally (Windows, 64 Bit). Wird von build.sh aufgerufen:
;   makensis -DVERSION=... -DSTAGE=... -DOUTFILE=... tally.nsi
; Installiert pro Benutzer (keine Admin-Rechte nötig) nach
; %LOCALAPPDATA%\Programs\Tally. Einstellungen liegen getrennt in %APPDATA%\Tally.

Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"

!define APP "Tally"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"

Name "${APP} ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "Software\${APP}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "${APP} ${VERSION}"

VIProductVersion "${VIVERSION}"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "FileDescription" "${APP} - Twitch Vote Tracker (Setup)"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" ""

!define MUI_ICON "tally.ico"
!define MUI_UNICON "tally.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "${APP} jetzt starten"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "German"

; Bricht ab, wenn Tally noch läuft (python.exe ist dann gesperrt).
!macro AbortIfRunning
  ${If} ${FileExists} "$INSTDIR\python\python.exe"
    ClearErrors
    FileOpen $0 "$INSTDIR\python\python.exe" a
    ${If} ${Errors}
      MessageBox MB_OK|MB_ICONEXCLAMATION "${APP} läuft noch. Bitte das ${APP}-Fenster schließen und das Setup erneut starten."
      Abort
    ${EndIf}
    FileClose $0
  ${EndIf}
!macroend

Function LaunchApp
  ExecShell "" "$SMPROGRAMS\${APP}.lnk"
FunctionEnd

Section "${APP} (erforderlich)" SecMain
  SectionIn RO
  !insertmacro AbortIfRunning

  ; Update: alte Programmdateien entfernen. Einstellungen liegen in %APPDATA%.
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"

  SetOutPath "$INSTDIR"
  File /r "${STAGE}/*"
  File "tally.ico"
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Arbeitsverzeichnis der Verknüpfungen = app-Ordner
  SetOutPath "$INSTDIR\app"
  CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\python\python.exe" '"$INSTDIR\app\tally_win.py"' "$INSTDIR\tally.ico" 0 SW_SHOWMINIMIZED "" "${APP} - Twitch Vote Tracker"

  WriteRegStr HKCU "Software\${APP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\tally.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  SectionGetSize ${SecMain} $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" $0
SectionEnd

Section "Desktop-Verknüpfung" SecDesktop
  SetOutPath "$INSTDIR\app"
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\python\python.exe" '"$INSTDIR\app\tally_win.py"' "$INSTDIR\tally.ico" 0 SW_SHOWMINIMIZED "" "${APP} - Twitch Vote Tracker"
SectionEnd

Section /o "Mit Windows starten" SecAutostart
  SetOutPath "$INSTDIR\app"
  CreateShortcut "$SMSTARTUP\${APP}.lnk" "$INSTDIR\python\python.exe" '"$INSTDIR\app\tally_win.py" --no-browser' "$INSTDIR\tally.ico" 0 SW_SHOWMINIMIZED "" "${APP} im Hintergrund starten"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "Programm, mitgeliefertes Python und Startmenü-Eintrag."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Legt eine Verknüpfung auf dem Desktop an."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecAutostart} "Startet ${APP} bei jeder Windows-Anmeldung minimiert, ohne den Browser zu öffnen."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  !insertmacro AbortIfRunning

  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  Delete "$SMSTARTUP\${APP}.lnk"

  ; Nur die eigenen Dateien entfernen, nie den ganzen Zielordner rekursiv.
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\tally.ico"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "Software\${APP}"

  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "Auch Einstellungen und gespeicherte Zugangsdaten löschen?$\r$\n($APPDATA\${APP})" IDNO keep_data
    RMDir /r "$APPDATA\${APP}"
  keep_data:
SectionEnd
