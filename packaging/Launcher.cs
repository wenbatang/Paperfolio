using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Launcher {
    [STAThread]
    static void Main() {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(folder, @".venv\Scripts\pythonw.exe");
        try {
            if (!File.Exists(python)) throw new IOException("请先在程序目录运行 start.cmd 完成安装。");
            Process.Start(new ProcessStartInfo(python, "app.py") {
                WorkingDirectory = folder, UseShellExecute = false
            });
        } catch (Exception error) {
            MessageBox.Show(error.Message, "Paperfolio");
        }
    }
}
