using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;

internal static class Installer {
    static void Install(string folder) {
        folder = Path.GetFullPath(folder);
        Directory.CreateDirectory(folder);
        string marker = Path.Combine(folder, ".paperfolio-install");
        if (!File.Exists(marker) && Directory.GetFileSystemEntries(folder).Length != 0)
            throw new IOException("请选择空文件夹，或选择之前通过安装程序安装的 Paperfolio 目录。");
        File.WriteAllText(marker, "Paperfolio");
        using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using (var zip = new ZipArchive(payload)) {
            foreach (ZipArchiveEntry item in zip.Entries) {
                string target = Path.GetFullPath(Path.Combine(folder, item.FullName));
                if (!target.StartsWith(folder.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase))
                    throw new IOException("安装包路径无效。");
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                item.ExtractToFile(target, true);
            }
        }
        var setup = new ProcessStartInfo("powershell.exe",
            "-NoProfile -ExecutionPolicy Bypass -File \"" + Path.Combine(folder, "setup.ps1") + "\"");
        setup.WorkingDirectory = folder;
        using (var process = Process.Start(setup)) {
            process.WaitForExit();
            if (process.ExitCode != 0)
                throw new IOException("依赖下载或安装失败。检查网络后重新运行安装程序，或在安装目录运行 start.cmd。");
        }
    }

    [STAThread]
    static int Main(string[] args) {
        Application.EnableVisualStyles();
        if (args.Length == 2 && args[0] == "--install") {
            try { Install(args[1]); return 0; }
            catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
        }
        using (var form = new Form()) {
            form.Text = "安装 Paperfolio 文献书房";
            form.ClientSize = new Size(480, 168);
            form.FormBorderStyle = FormBorderStyle.FixedDialog;
            form.MaximizeBox = false;
            form.StartPosition = FormStartPosition.CenterScreen;
            form.Font = new Font("Microsoft YaHei UI", 9);
            var label = new Label { Text = "安装到", Left = 16, Top = 15, AutoSize = true };
            var path = new TextBox { Left = 16, Top = 43, Width = 360,
                Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Paperfolio") };
            var browse = new Button { Left = 386, Top = 41, Width = 78, Text = "浏览…" };
            browse.Click += delegate {
                using (var dialog = new FolderBrowserDialog()) {
                    dialog.Description = "选择 Paperfolio 的安装文件夹";
                    dialog.SelectedPath = path.Text;
                    if (dialog.ShowDialog(form) == DialogResult.OK) path.Text = dialog.SelectedPath;
                }
            };
            var note = new Label { Left = 16, Top = 83, Width = 452, Height = 36,
                Text = "首次安装会联网准备 Python 和阅读组件。附件保存位置可在书房设置中更改。" };
            var start = new Button { Text = "安装", Left = 380, Top = 126, Width = 84, DialogResult = DialogResult.OK };
            form.Controls.AddRange(new Control[] { label, path, browse, note, start });
            form.AcceptButton = start;
            while (form.ShowDialog() == DialogResult.OK) {
                try {
                    if (String.IsNullOrWhiteSpace(path.Text) || !Path.IsPathRooted(path.Text))
                        throw new IOException("请输入完整的安装目录。");
                    Install(path.Text);
                    if (MessageBox.Show("安装完成。现在打开文献书房？", "Paperfolio", MessageBoxButtons.YesNo) == DialogResult.Yes)
                        Process.Start(Path.Combine(path.Text, "Paperfolio.exe"));
                    return 0;
                } catch (Exception error) {
                    MessageBox.Show(error.Message, "安装未完成");
                }
            }
        }
        return 0;
    }
}
