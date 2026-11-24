# Zotero 桌面同步与 Word 引用

仅在项目设置 `use_zotero: true`，且用户要求归档或导出动态引文时执行。使用 Zotero 桌面个人库，先确认目标分类是本项目分类。两个模式各用一个新的项目内任务目录。以下命令从 LRS 根目录运行。

## Python 环境与依赖

先遵循当前项目的环境约定。下文的 `python` 表示该环境里的 Python 3。可使用系统 Python、项目的虚拟环境或 Conda 环境，也可按机器设置改用 `python3` 或解释器的绝对路径。只有当前项目要求使用名为 `review` 的 Conda 环境时，才先运行 `conda activate review`，或把示例中的 `python` 替换为 `conda run -n review python`。

- 准备纳入库归档任务只需要 Python 标准库。执行同步任务需要 Zotero 桌面端，脚本由 Zotero 自带的 JavaScript 环境运行。
- 准备 Word 同步任务需要 Python 和支持 `--citeproc` 的 Pandoc。导出 Word 文件时，还需要在所选 Python 环境中安装 `python-docx` 和 `lxml`。可先用 `python -c "import docx, lxml"` 检查。Pandoc 不在 PATH 时，为命令添加 `--pandoc "<Pandoc 可执行文件路径>"`。
- 刷新和验证动态引文时，需要桌面 Word 和 Zotero Word 插件。

## 选择同步范围

- **纳入库归档**使用已锁定的 `03-screening/included.tsv` 和去重库 `02-records/library.csv`。运行：

  `python skills/zotero-library-sync/scripts/desktop_workflow.py prepare --mode archive --project "<project>" --collection "<project>-included" --job "<project>/04-library/zotero-archive-01"`

- **Word 动态引文**使用本次交付的单一 Markdown。按大纲顺序纳入所有选定章节和实际交付的图注、图链接、表格，排除备选稿、主题清单和未交付的图表。保留图片相对于此文件的路径。引用可使用 `(Smith, 2020; E014; Jones, 2021; E025)` 或 `[@Smith2020; @Jones2021]`。由 Pandoc 从整份稿件提取引文，包括表格和图注。特殊位置的证据 ID 需在导出副本里转换为 Pandoc 引文。当前动态导出支持普通括号引用。如果输入含页码、前后缀或作者叙述式引文，保留原意并报告需要在 Word 中用插件完成这些引文。运行：

  `python skills/zotero-library-sync/scripts/desktop_workflow.py prepare --mode word --project "<project>" --source "<assembled.md>" --collection "<project>" --job "<project>/04-library/zotero-word-01"`

## 批量运行 Zotero

1. 用当前会话可用的桌面工具选择 Zotero。在 Zotero 打开 **Tools → Developer → Run JavaScript** 并启用异步函数模式。把刚生成的 `run-in-zotero.js` 作为一个批次运行。仅执行该项目任务生成的代码。若 Zotero 无法访问，归档模式提供 RIS，Word 模式报告动态导出待完成。仅在用户要求时提供已标明的静态稿。
2. 核对 `mapping.json` 的分类、`mappings` 和 `failures`，汇报新增、复用、失败数量。代码保留已有分类和馆藏条目；遇到歧义时报告冲突并跳过。重复运行使用新任务目录及同一分类名，或从同一任务重新运行脚本以重新生成映射。一个任务目录一次只运行一个 Zotero 会话。
3. 归档到此完成。分类主题清单只在用户要求时另外确认。PDF 和笔记依照原工作流处理。

## 生成并验证 Word

取得锁定期刊的 CSL 文件，确认所用样式与 Zotero 中的样式一致。需要 Word 模板时加 `--reference-doc`。输出路径应为新文件。

`python skills/zotero-library-sync/scripts/desktop_workflow.py export --job "<project>/04-library/zotero-word-01" --csl "<journal.csl>" --output "<project>/10-polish/manuscript-zotero.docx"`

未解析引用键、缺失映射、同步失败或分类不符会阻止动态导出。导出后在桌面 Word 的 **Zotero → Refresh** 检查正文、图注和表格中的引文以及文末参考文献表。编号样式可在独立样稿中交换两处引文，刷新后确认编号和文献表同步更新。无法运行 Word 插件时，报告动态字段已生成及刷新验证待完成。修订已存在的 live DOCX 时，遵循 `review-writing` 中保护引用字段的流程。
