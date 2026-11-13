# BidFlow AI 招投标 1.1.1

面向政府及企业采购和工程项目的 AI 招投标工具，支持项目雷达扫描、标书拆解和投标文件初稿撰写。

## Windows 启动

解压到新目录，安装 Python 3.8 或更高版本，双击 `self_check.bat`，再双击 `start.bat`。
默认访问 http://127.0.0.1:8080/。可上传 DOCX 标书，核对评分项、废标风险和原文位置，并生成 Word 初稿。

## 需求雷达

在解压目录打开命令提示符，按需运行：

```bat
python collector\daily.py 公厕
```

这条命令从中国政府采购网检索公开公告，按原始链接去重入库，并在 `data/reports/` 生成公厕可投 HTML 清单。
需要每日自动运行时，在 Windows 任务计划程序中添加每日任务。程序填 Python 解释器完整路径，参数填 `collector\daily.py 公厕`，起始目录填 BidFlow 解压目录。
也可通过网页按地区和金额筛选，导出 HTML 和 CSV。请以原公告核对资格、金额和投标截止日期。

离线试用可先运行 `python collector/daily.py --input data/sample/notices.example.jsonl` 导入合成样例。

开源许可证为 Apache 2.0。提交投标文件前请人工核对全部内容。
