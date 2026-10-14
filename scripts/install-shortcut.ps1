param([string]$Executable = '')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $Executable) { $Executable = Join-Path $projectRoot 'dist\FilePilot\FilePilot.exe' }
$Executable = (Resolve-Path -LiteralPath $Executable -ErrorAction Stop).Path
if ([System.IO.Path]::GetExtension($Executable) -ne '.exe') { throw 'Select a built Windows executable.' }
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (-not $desktop -or -not (Test-Path -LiteralPath $desktop)) { throw 'Windows desktop directory is unavailable.' }
$shortcutPath = Join-Path $desktop 'FilePilot.lnk'
$shell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $shortcutPath) {
    $prior = $shell.CreateShortcut($shortcutPath)
    if ($prior.TargetPath -ne $Executable) { throw 'An existing FilePilot shortcut points to another application.' }
}
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $Executable
$shortcut.WorkingDirectory = Split-Path -Parent $Executable
$shortcut.IconLocation = "$Executable,0"
$shortcut.Description = 'FilePilot - Local file organization with preview and undo'
$shortcut.WindowStyle = 1
$shortcut.Save()

if (-not ('FilePilotShortcutIdentity' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
internal class FilePilotShellLink { }

[StructLayout(LayoutKind.Sequential, Pack=4)]
internal struct FilePilotPropertyKey {
    public Guid FormatId;
    public uint PropertyId;
}

[StructLayout(LayoutKind.Sequential)]
internal struct FilePilotPropVariant {
    public ushort Type;
    public ushort reserved1, reserved2, reserved3;
    public IntPtr Value;
    public IntPtr extra;
}

[ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface FilePilotPropertyStore {
    [PreserveSig] int GetCount(out uint count);
    [PreserveSig] int GetAt(uint index, out FilePilotPropertyKey key);
    [PreserveSig] int GetValue(ref FilePilotPropertyKey key, out FilePilotPropVariant value);
    [PreserveSig] int SetValue(ref FilePilotPropertyKey key, ref FilePilotPropVariant value);
    [PreserveSig] int Commit();
}

public static class FilePilotShortcutIdentity {
    [DllImport("ole32.dll")] private static extern int PropVariantClear(ref FilePilotPropVariant value);
    [DllImport("shell32.dll", CharSet=CharSet.Unicode)]
    private static extern void SHChangeNotify(uint eventId, uint flags, string item1, IntPtr item2);

    public static string SetAndRead(string path, string appId) {
        object link = new FilePilotShellLink();
        var key = new FilePilotPropertyKey { FormatId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), PropertyId = 5 };
        var input = new FilePilotPropVariant { Type = 31, Value = Marshal.StringToCoTaskMemUni(appId) };
        FilePilotPropVariant output = new FilePilotPropVariant();
        try {
            var file = (IPersistFile)link;
            file.Load(path, 2);
            var store = (FilePilotPropertyStore)link;
            Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref input));
            Marshal.ThrowExceptionForHR(store.Commit());
            file.Save(path, true);
            Marshal.ThrowExceptionForHR(store.GetValue(ref key, out output));
            return Marshal.PtrToStringUni(output.Value);
        } finally {
            PropVariantClear(ref input);
            PropVariantClear(ref output);
            Marshal.FinalReleaseComObject(link);
            SHChangeNotify(0x00002000, 0x0005, path, IntPtr.Zero);
        }
    }

    public static void RefreshIcon(string executable) {
        SHChangeNotify(0x00002000, 0x0005, executable, IntPtr.Zero);
    }
}
'@
}
$identity = [FilePilotShortcutIdentity]::SetAndRead($shortcutPath, 'FilePilot.Desktop')
if ($identity -ne 'FilePilot.Desktop') { throw 'Shortcut identity verification failed.' }
[FilePilotShortcutIdentity]::RefreshIcon($Executable)
$check = $shell.CreateShortcut($shortcutPath)
if ($check.TargetPath -ne $Executable -or $check.IconLocation -ne "$Executable,0") { throw 'Shortcut verification failed.' }
[pscustomobject]@{Shortcut=$shortcutPath;Executable=$check.TargetPath;Icon=$check.IconLocation;
    WorkingDirectory=$check.WorkingDirectory;AppUserModelId=$identity} | ConvertTo-Json
