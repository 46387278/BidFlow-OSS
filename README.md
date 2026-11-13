# BidFlow AI 招投标 1.1.1

面向政府及企业采购和工程项目的 AI 招投标工具，支持项目雷达扫描、标书拆解和投标文件初稿撰写。

## Windows 启动

解压到新目录，安装 Python 3.8 或更高版本，双击 `self_check.bat`，再双击 `start.bat`。
默认访问 http://127.0.0.1:8080/。可上传 DOCX 标书，核对评分项、废标风险和原文位置，并生成 Word 初稿。

## 需求雷达

在解压目录打开命令提示符，按需运行：

```bat
python collector\ccgp_collect.py 公厕
python collector\radar_brief.py
```

第一条从中国政府采购网检索公开公告，并按公告链接去重入库。第二条生成公厕相关 HTML 清单，存入 `data/reports/`。
也可通过网页按地区和金额筛选，导出 HTML 和 CSV。请以原公告核对资格、金额和投标截止日期。

离线试用可先运行 `python collector/ingest.py data/sample/notices.example.jsonl` 导入合成样例。

开源许可证为 Apache 2.0。提交投标文件前请人工核对全部内容。
