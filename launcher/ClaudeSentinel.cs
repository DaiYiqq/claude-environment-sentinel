using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Claude Environment Sentinel")]
[assembly: AssemblyProduct("Claude Environment Sentinel")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        try
        {
            string baseDir = Path.GetDirectoryName(Application.ExecutablePath);
            string root = FindRoot(baseDir);
            if (root == null)
            {
                ShowError(
                    "找不到 Sentinel 项目目录。\n\n" +
                    "请把 ClaudeSentinel.exe 放在项目根目录（与 sentinel 文件夹同级），\n" +
                    "或放在项目根目录的 dist 子目录中。"
                );
                return;
            }

            string python = FindPython(root);
            if (python == null)
            {
                ShowError(
                    "找不到 Python。\n\n" +
                    "Sentinel 桌面版需要本机 Python 3.10+，或使用包含 python\\ 运行时的便携版。\n" +
                    "请安装 Python，并在安装时勾选 Add python.exe to PATH。\n\n" +
                    "安装后重新双击 ClaudeSentinel.exe。"
                );
                return;
            }

            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = python;
            info.Arguments = "-m sentinel";
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.WindowStyle = ProcessWindowStyle.Hidden;
            Process.Start(info);
        }
        catch (Exception ex)
        {
            ShowError("启动 Claude Environment Sentinel 失败：\n\n" + ex.Message);
        }
    }

    private static string FindRoot(string start)
    {
        if (String.IsNullOrEmpty(start))
        {
            return null;
        }
        DirectoryInfo dir = new DirectoryInfo(start);
        for (int i = 0; i < 6 && dir != null; i++)
        {
            if (File.Exists(Path.Combine(dir.FullName, "sentinel", "__main__.py")))
            {
                return dir.FullName;
            }
            dir = dir.Parent;
        }
        return null;
    }

    private static string FindPython(string root)
    {
        if (!String.IsNullOrEmpty(root))
        {
            string localPython = Path.Combine(root, "python", "pythonw.exe");
            if (File.Exists(localPython))
            {
                return localPython;
            }
            localPython = Path.Combine(root, "python", "python.exe");
            if (File.Exists(localPython))
            {
                return localPython;
            }
        }

        string path = Environment.GetEnvironmentVariable("PATH");
        if (!String.IsNullOrEmpty(path))
        {
            string[] parts = path.Split(new char[] { ';' }, StringSplitOptions.RemoveEmptyEntries);
            for (int i = 0; i < parts.Length; i++)
            {
                string folder = parts[i].Trim().Trim('"');
                if (folder.Length == 0)
                {
                    continue;
                }
                string candidate = FindInFolder(folder);
                if (candidate != null)
                {
                    return candidate;
                }
            }
        }

        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string programs = Path.Combine(local, "Programs", "Python");
        if (Directory.Exists(programs))
        {
            string[] dirs = Directory.GetDirectories(programs);
            Array.Sort(dirs);
            Array.Reverse(dirs);
            for (int i = 0; i < dirs.Length; i++)
            {
                string candidate = FindInFolder(dirs[i]);
                if (candidate != null)
                {
                    return candidate;
                }
            }
        }

        string[] versions = new string[] { "314", "313", "312", "311", "310" };
        for (int i = 0; i < versions.Length; i++)
        {
            string candidate = Path.Combine("C:\\", "Python" + versions[i], "pythonw.exe");
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }
        return null;
    }

    private static string FindInFolder(string folder)
    {
        string[] names = new string[] { "pythonw.exe", "python.exe" };
        for (int i = 0; i < names.Length; i++)
        {
            string candidate = Path.Combine(folder, names[i]);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }
        return null;
    }

    private static void ShowError(string message)
    {
        MessageBox.Show(
            message,
            "Claude Environment Sentinel",
            MessageBoxButtons.OK,
            MessageBoxIcon.Error
        );
    }
}
