using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;
[assembly: System.Reflection.AssemblyTitle("祀音")]
[assembly: System.Reflection.AssemblyProduct("祀音语音工作台")]
[assembly: System.Reflection.AssemblyVersion("1.1.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.1.0.0")]
internal static class Launcher {
    private static readonly object LogLock = new object();
    [STAThread] private static int Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string app = Path.Combine(root, "app");
        string log = Path.Combine(app, "logs", "desktop.log");
        try {
            Directory.CreateDirectory(Path.GetDirectoryName(log));
            var start = new ProcessStartInfo(Path.Combine(app, "python", "pythonw.exe"));
            start.Arguments = "\"" + Path.Combine(app, "desktop", "launch.py") + "\"";
            start.WorkingDirectory = app;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.StandardOutputEncoding = Encoding.UTF8;
            start.StandardErrorEncoding = Encoding.UTF8;
            start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            start.EnvironmentVariables["GSV_NO_BROWSER"] = "1";
            using (var child = new Process()) {
                child.StartInfo = start;
                DataReceivedEventHandler capture = (sender, e) => {
                    if (e.Data != null) lock (LogLock) File.AppendAllText(log, DateTime.Now.ToString("s") + " " + e.Data + Environment.NewLine, Encoding.UTF8);
                };
                child.OutputDataReceived += capture;
                child.ErrorDataReceived += capture;
                child.Start(); child.BeginOutputReadLine(); child.BeginErrorReadLine(); child.WaitForExit();
                if (child.ExitCode != 0) MessageBox.Show("启动失败，请查看应用目录 app\\logs\\desktop.log。", "祀音", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return child.ExitCode;
            }
        } catch (Exception e) {
            MessageBox.Show("无法启动语音工作台：" + e.Message, "祀音", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
