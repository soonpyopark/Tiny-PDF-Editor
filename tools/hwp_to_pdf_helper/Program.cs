// x86 helper: convert HWP/HWPX to PDF via running Hancom Hangul automation (ROT).
// Built for 32-bit because Hangul COM is 32-bit only.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Threading;
using Microsoft.Win32;

[assembly: AssemblyTitle("Tiny PDF Editor HWP helper")]
[assembly: AssemblyProduct("Tiny PDF Editor")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class Program
{
    private const int ExitOk = 0;
    private const int ExitUsage = 1;
    private const int ExitNoHancom = 2;
    private const int ExitAutomation = 3;
    private const int ExitConvert = 4;

    [DllImport("ole32.dll")]
    private static extern int GetRunningObjectTable(int reserved, out IRunningObjectTable pprot);

    [DllImport("ole32.dll")]
    private static extern int CreateBindCtx(int reserved, out IBindCtx ppbc);

    [DllImport("oleaut32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    private static extern int LoadTypeLibEx(
        string file,
        int regKind,
        out ITypeLib typeLib);

    [DllImport("oleaut32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    private static extern int RegisterTypeLibForUser(
        ITypeLib typeLib,
        string fullPath,
        string helpDir);

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length < 2)
            {
                Console.Error.WriteLine("usage: hwp_to_pdf_helper.exe <input.hwp|hwpx> <output.pdf> [hwp.exe]");
                return ExitUsage;
            }

            string src = Path.GetFullPath(args[0]);
            string pdf = Path.GetFullPath(args[1]);
            string hwpExe = args.Length > 2 ? args[2] : FindHwpExe();
            if (hwpExe == null)
                hwpExe = "";

            if (!File.Exists(src))
            {
                Console.Error.WriteLine("input not found: " + src);
                return ExitConvert;
            }
            if (string.IsNullOrEmpty(hwpExe) || !File.Exists(hwpExe))
            {
                Console.Error.WriteLine("HANCOM_NOT_FOUND");
                return ExitNoHancom;
            }

            EnsureFilePathCheckerRegistered();
            EnsureHwpTypeLibraryRegistered(hwpExe);

            string pdfDir = Path.GetDirectoryName(pdf);
            if (string.IsNullOrEmpty(pdfDir))
                pdfDir = ".";
            Directory.CreateDirectory(pdfDir);
            if (File.Exists(pdf))
            {
                try { File.Delete(pdf); } catch { /* ignore */ }
            }

            bool startedByUs = false;
            object hwp = FindHwpInRot();
            if (hwp == null)
            {
                startedByUs = true;
                var psi = new ProcessStartInfo(hwpExe)
                {
                    UseShellExecute = true,
                    WindowStyle = ProcessWindowStyle.Minimized,
                };
                Process.Start(psi);
                hwp = WaitForHwpInRot(TimeSpan.FromSeconds(45));
            }

            if (hwp == null)
            {
                Console.Error.WriteLine("HANCOM_AUTOMATION_UNAVAILABLE");
                return ExitAutomation;
            }

            try
            {
                try
                {
                    Invoke(hwp, "RegisterModule", "FilePathCheckDLL", "FilePathCheckerModule");
                }
                catch
                {
                    // Optional; Open may still succeed when Hangul is already running.
                }

                object opened = Invoke(
                    hwp,
                    "Open",
                    src,
                    "",
                    "lock:false;forceopen:true;suspendpassword:true;");
                if (opened != null && opened.GetType() == typeof(bool) && !(bool)opened)
                {
                    Console.Error.WriteLine("open failed");
                    return ExitConvert;
                }

                try
                {
                    object saved = Invoke(hwp, "SaveAs", pdf, "PDF", "");
                    bool savedOk = saved != null && saved.GetType() == typeof(bool) && (bool)saved;
                    if (!savedOk && !File.Exists(pdf))
                    {
                        Console.Error.WriteLine("SaveAs failed");
                        return ExitConvert;
                    }
                }
                finally
                {
                    try { Invoke(hwp, "Run", "FileClose"); } catch { /* ignore */ }
                }

                if (!File.Exists(pdf) || new FileInfo(pdf).Length <= 0)
                {
                    Console.Error.WriteLine("pdf not created");
                    return ExitConvert;
                }

                Console.WriteLine("OK " + pdf);
                return ExitOk;
            }
            finally
            {
                if (startedByUs)
                {
                    try { Invoke(hwp, "Quit"); } catch { /* ignore */ }
                    try { Marshal.FinalReleaseComObject(hwp); } catch { /* ignore */ }
                }
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.GetBaseException().Message);
            return ExitConvert;
        }
    }

    private static object Invoke(object target, string name, params object[] args)
    {
        return target.GetType().InvokeMember(
            name,
            BindingFlags.InvokeMethod,
            null,
            target,
            args);
    }

    private static object WaitForHwpInRot(TimeSpan timeout)
    {
        var sw = Stopwatch.StartNew();
        while (sw.Elapsed < timeout)
        {
            object hwp = FindHwpInRot();
            if (hwp != null)
                return hwp;
            Thread.Sleep(400);
        }
        return null;
    }

    private static object FindHwpInRot()
    {
        IRunningObjectTable rot;
        if (GetRunningObjectTable(0, out rot) != 0 || rot == null)
            return null;
        IEnumMoniker enumMoniker;
        rot.EnumRunning(out enumMoniker);
        if (enumMoniker == null)
            return null;
        enumMoniker.Reset();
        var monikers = new IMoniker[1];
        IntPtr fetched = IntPtr.Zero;
        IBindCtx ctx;
        CreateBindCtx(0, out ctx);
        while (enumMoniker.Next(1, monikers, fetched) == 0)
        {
            string name;
            monikers[0].GetDisplayName(ctx, null, out name);
            if (!string.IsNullOrEmpty(name) && name.StartsWith("!HwpObject", StringComparison.Ordinal))
            {
                object obj;
                rot.GetObject(monikers[0], out obj);
                return obj;
            }
        }
        return null;
    }

    private static string FindHwpExe()
    {
        string[] pathValues =
        {
            ReadRegString(Registry.LocalMachine, @"SOFTWARE\WOW6432Node\HNC\Shared", "Hnc Path130"),
            ReadRegString(Registry.LocalMachine, @"SOFTWARE\HNC\Shared", "Hnc Path130"),
            ReadRegString(Registry.LocalMachine, @"SOFTWARE\WOW6432Node\HNC\Shared", "Hnc Path120"),
            ReadRegString(Registry.LocalMachine, @"SOFTWARE\WOW6432Node\HNC\Shared", "Hnc Path110"),
        };
        foreach (string root in pathValues)
        {
            if (string.IsNullOrWhiteSpace(root))
                continue;
            string[] candidates =
            {
                Path.Combine(root, "HOffice130", "Bin", "Hwp.exe"),
                Path.Combine(root, "HOffice120", "Bin", "Hwp.exe"),
                Path.Combine(root, "HOffice110", "Bin", "Hwp.exe"),
                Path.Combine(root, "Bin", "Hwp.exe"),
            };
            foreach (string c in candidates)
            {
                if (File.Exists(c))
                    return c;
            }
        }

        string pf86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
        foreach (string rel in new[]
        {
            @"Hnc\Office 2024\HOffice130\Bin\Hwp.exe",
            @"HNC\Office 2024\HOffice130\Bin\Hwp.exe",
            @"Hnc\Office 2022\HOffice120\Bin\Hwp.exe",
            @"Hnc\Office 2020\HOffice110\Bin\Hwp.exe",
        })
        {
            string p = Path.Combine(pf86, rel);
            if (File.Exists(p))
                return p;
        }
        return null;
    }

    private static string ReadRegString(RegistryKey root, string subkey, string name)
    {
        try
        {
            using (RegistryKey key = root.OpenSubKey(subkey))
            {
                object value = key == null ? null : key.GetValue(name);
                return value as string;
            }
        }
        catch
        {
            return null;
        }
    }

    private static void EnsureFilePathCheckerRegistered()
    {
        string dll = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "FilePathCheckerModule.dll");
        if (!File.Exists(dll))
        {
            // When invoked from python vendor folder, helper sits next to the DLL.
            string helperDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            if (string.IsNullOrEmpty(helperDir))
                helperDir = ".";
            dll = Path.Combine(helperDir, "FilePathCheckerModule.dll");
        }
        if (!File.Exists(dll))
            return;
        try
        {
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(@"Software\HNC\HwpAutomation\Modules"))
            {
                if (key != null)
                    key.SetValue("FilePathCheckerModule", dll, RegistryValueKind.String);
            }
        }
        catch
        {
            // ignore
        }
    }

    private static void EnsureHwpTypeLibraryRegistered(string hwpExe)
    {
        string binDir = Path.GetDirectoryName(hwpExe);
        if (string.IsNullOrEmpty(binDir))
            return;
        string tlbPath = Path.Combine(binDir, "HwpObject.tlb");
        if (!File.Exists(tlbPath))
            return;

        ITypeLib typeLib = null;
        try
        {
            // REGKIND_NONE (2): load without requiring administrator privileges.
            int loaded = LoadTypeLibEx(tlbPath, 2, out typeLib);
            if (loaded != 0 || typeLib == null)
                return;
            int registered = RegisterTypeLibForUser(typeLib, tlbPath, binDir);
            if (registered != 0)
                Marshal.ThrowExceptionForHR(registered);
        }
        finally
        {
            if (typeLib != null)
            {
                try { Marshal.FinalReleaseComObject(typeLib); } catch { /* ignore */ }
            }
        }
    }
}
