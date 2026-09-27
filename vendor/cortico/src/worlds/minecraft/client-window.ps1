# 找一个进程名下的主窗口:有没有出来,以及改标题。
#
# 认哪扇窗只认 OwnerPid:调用方托管着那个进程,窗口归属是唯一无歧义的凭据。
# 没有按标题找的路——同一台机器上常有第二份同名同标题的客户端(人自己玩的那份)。
#
# 用法:
#   探测: powershell -File client-window.ps1 -OwnerPid 1234
#   改标题: powershell -File client-window.ps1 -OwnerPid 1234 -SetTitle CortiCam
# 输出:一行 JSON {ok, hwnd, title, error}
param(
  [Parameter(Mandatory = $true)][int]$OwnerPid,
  [string]$SetTitle = ''
)

$ErrorActionPreference = 'Stop'

Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class MinecraftWin {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr hWnd);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern bool SetWindowText(IntPtr hWnd, string text);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
'@

function Write-Result($obj) {
  Write-Output ($obj | ConvertTo-Json -Compress)
}

# 一个进程可能有多扇窗(闪屏、对话框),取面积最大的那扇。
# 一扇都没有 = 这个客户端还没就绪,由调用方接着等,不去别处找。
# 参数不能叫 $pid:$PID 是 PowerShell 当前进程号,只读。
function Find-OwnerWindow([int]$targetPid) {
  $script:OwnerPid = $targetPid
  $script:best = [IntPtr]::Zero
  $script:bestArea = 0
  $script:bestTitle = ''
  $cb = [MinecraftWin+EnumProc] {
    param($hWnd, $lParam)
    if (-not [MinecraftWin]::IsWindowVisible($hWnd)) { return $true }
    if ([MinecraftWin]::IsIconic($hWnd)) { return $true }
    $len = [MinecraftWin]::GetWindowTextLength($hWnd)
    if ($len -le 0) { return $true }
    $sb = New-Object System.Text.StringBuilder ($len + 1)
    [void][MinecraftWin]::GetWindowText($hWnd, $sb, $sb.Capacity)
    $title = $sb.ToString()
    $wpid = 0
    [void][MinecraftWin]::GetWindowThreadProcessId($hWnd, [ref]$wpid)
    if ($wpid -ne $script:OwnerPid) { return $true }
    $r = New-Object MinecraftWin+RECT
    [void][MinecraftWin]::GetWindowRect($hWnd, [ref]$r)
    $area = ($r.Right - $r.Left) * ($r.Bottom - $r.Top)
    if ($area -gt $script:bestArea) {
      $script:bestArea = $area
      $script:best = $hWnd
      $script:bestTitle = $title
    }
    return $true
  }
  [void][MinecraftWin]::EnumWindows($cb, [IntPtr]::Zero)
  return @{ hwnd = $script:best; title = $script:bestTitle }
}

try {
  $found = Find-OwnerWindow $OwnerPid
  $best = $found.hwnd

  if ($best -eq [IntPtr]::Zero) {
    Write-Result @{ ok = $false; error = 'no-window' }
    exit 0
  }

  if ($SetTitle) {
    [void][MinecraftWin]::SetWindowText($best, $SetTitle)
    Write-Result @{ ok = $true; hwnd = [int64]$best; title = $SetTitle }
    exit 0
  }

  Write-Result @{ ok = $true; hwnd = [int64]$best; title = $found.title }
} catch {
  Write-Result @{ ok = $false; error = $_.Exception.Message }
}
