import { spawn } from 'node:child_process';

/**
 * Windows: removes the small icon in front of the window title ("[icon] <앱 이름>")
 * while keeping the taskbar / Alt+Tab icon.
 *
 * Electron's `icon` option sets the title-bar icon and the taskbar icon together, so
 * the only way to drop just the title-bar one is to give the window a transparent
 * *small* icon (WM_SETICON / ICON_SMALL) and leave the big one alone. Electron has
 * no API for that, so a short-lived PowerShell does the Win32 call. Best effort:
 * on any failure the window simply keeps its icon.
 *
 * @param {import('electron').BrowserWindow} win
 * @param {number} [timeoutMs]
 * @returns {Promise<void>} settles when done (never rejects)
 */
export function hideTitleBarIcon(win, timeoutMs = 4000) {
  if (process.platform !== 'win32') return Promise.resolve();

  return new Promise((resolve) => {
    try {
      const raw = win.getNativeWindowHandle();
      const hwnd = raw.length >= 8 ? raw.readBigUInt64LE(0) : BigInt(raw.readUInt32LE(0));

      const script = `
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class FrameWinIcon {
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
}
"@
$bmp = New-Object System.Drawing.Bitmap 16, 16, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
[FrameWinIcon]::SendMessage([IntPtr]::new([long]${hwnd}), 0x80, [IntPtr]::Zero, $bmp.GetHicon()) | Out-Null
`;
      const child = spawn(
        'powershell.exe',
        ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(script, 'utf16le').toString('base64')],
        { windowsHide: true, stdio: 'ignore' },
      );
      const timer = setTimeout(() => {
        child.kill();
        resolve();
      }, timeoutMs);
      const done = () => {
        clearTimeout(timer);
        resolve();
      };
      child.once('error', done);
      child.once('exit', done);
    } catch {
      resolve();
    }
  });
}
