# 翻译与导读安装教程

先导入一篇有文字层的 PDF。第一次试译建议在页码框填 `1`。任务完成后，在该篇论文的 **附件** 栏打开译文或双语版。

## 安装 PDF2Zh 保留排版引擎

1. 打开 Paperfolio 的安装目录。源码用户打开含 `start.cmd` 的项目目录。
2. 双击 **install-layout.cmd**。脚本会把 `pdf2zh-next==2.10.2` 安装到该程序自己的 Python 环境，然后下载并校验 BabelDOC 的字体和排版模型。下载期间保持联网，结束时窗口会显示 `PDF2Zh is ready`。
3. 重新打开 **翻译原文**，选 **PDF2Zh · 保留排版**，再选翻译服务。它会生成一份译文 PDF 和一份双语 PDF。**段落对照** 模式随基础安装提供，可直接使用。

如需自定义 Python 包下载源，在安装目录打开 PowerShell，运行以下命令。将示例网址换成自己的兼容 PyPI 镜像。字体和排版模型仍由 BabelDOC 从其资源服务器下载。若预热中断，可重新运行最后一行。

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Layout -IndexUrl https://pypi.org/simple
.\.venv\Scripts\pdf2zh_next.exe --warmup
```

离线机器可按上游说明，在联网机器生成资源包，再使用同版命令行导入。Python 包与排版资源需要分别准备。[PDF2Zh 项目](https://github.com/PDFMathTranslate/PDFMathTranslate-next) · [命令行与离线资源](https://github.com/PDFMathTranslate/PDFMathTranslate-next/blob/main/docs/en/advanced/advanced.md)

## 微软翻译

1. 在 Azure 门户创建或选择 Translator 资源。在资源的 **密钥和终结点** 页面查看密钥与区域。
2. 选 **翻译原文 → 翻译服务 → 微软翻译 · Azure**，填入一个密钥。区域资源或多服务资源还需要填写实际区域标识，例如 `eastasia`。全球单服务资源可留空。此入口使用 Azure 全球公共翻译端点。
3. 选语言和页码，开始翻译。遇到 401 或 403，先核对密钥、区域、资源访问设置和额度。[微软翻译 API](https://learn.microsoft.com/azure/ai-services/translator/text-translation/reference/v3/translate)

## Google 翻译

1. 在 Google Cloud 项目启用结算和 **Cloud Translation API**，创建 API 密钥。可将密钥限制为仅访问该 API。
2. 选 **翻译原文 → 翻译服务 → Google Cloud 翻译**，粘贴密钥，选好语言和页码后开始。程序调用 Cloud Translation Basic v2。403 时检查 API 是否启用、密钥限制和结算状态，429 时检查配额。[凭据配置](https://cloud.google.com/translate/docs/authentication) · [文本翻译示例](https://cloud.google.com/translate/docs/translate-text)

这两个服务都会接收所选页中的文字，并按云账号的配额或价格计量。手动填写的密钥仅用于当前翻译窗口。希望下次自动填入时，可在 Windows 用户环境变量里设置 `AZURE_TRANSLATOR_KEY`、`AZURE_TRANSLATOR_REGION` 或 `GOOGLE_TRANSLATE_API_KEY`，然后重新启动 Paperfolio。已有 PDF2Zh TOML 的用户也可以在保留排版模式选 **PDF2Zh 配置文件**。

## 在 Windows 上部署 Ollama 导读

1. 下载并运行 Windows 版 Ollama，安装完成后打开 Ollama。默认本地服务地址为 `http://127.0.0.1:11434`。[Windows 下载](https://ollama.com/download/windows) · [安装与服务说明](https://docs.ollama.com/windows)
2. 如果希望模型下载到其他盘，先在 Windows 用户环境变量中设置 `OLLAMA_MODELS`，例如 `E:\software\ollama\models`。从系统托盘退出 Ollama 并重新启动，再下载模型。已有模型可以继续使用。[模型保存位置](https://docs.ollama.com/windows)
3. 在 PowerShell 运行以下命令。第一行下载示例模型，第二行列出本机模型，第三行验证 Paperfolio 使用的本机 API。已有支持文本生成的模型时，可直接从第二行开始。[模型页](https://ollama.com/library/qwen3.5:9b) · [模型列表 API](https://docs.ollama.com/api/tags)

```powershell
ollama pull qwen3.5:9b
ollama list
(Invoke-RestMethod http://127.0.0.1:11434/api/tags).models.name
```

4. 选择论文，打开 **条目信息 → 论文导读**。程序会自动识别模型，为背景、亮点、方法对比、扩展方向整理要点。点击页码可核对原文。已生成的导读保存在本地库中。

连接被拒绝时，先打开 Ollama，或在单独终端运行 `ollama serve` 并保留终端。若提示端口已被使用，先用上面的 API 命令检查已有服务。模型列表为空时先完成一次 `ollama pull`。导读需要可提取的正文文字，纯扫描件可先做 OCR。
