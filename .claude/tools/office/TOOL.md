# OfficeCLI Word撰写与核验

适用于创建或修改 DOCX。新稿应先完成全文和整批 JSON 操作，再开始编辑；已有文档只做本轮要求的修改，不重建原件。

普通文章默认只用内置标题层级，不添加封面、目录、页眉页脚或页码；用户明确要求或所选模板包含时才添加。模板和超长报告遵循其结构要求。

## 工具边界

- 文档创建和修改必须通过 `mcp__office__officecli` MCP 完成。不要通过 Bash 或 shell 直接调用 `officecli`，不要用脚本读写 DOCX XML；文件交付确需复制时可使用已有发布流程。
- 普通撰写不加载完整 Word Skill（例如 `load_skill word`），也不探测系统字体、遍历工作目录或重复读取完整帮助。缺少具体命令语法时，只查一次对应的 OfficeCLI MCP 帮助。
- 普通撰写不编写 Python-docx 或 docx-js 临时文档生成器，也不通过脚本修复 OfficeCLI 产物；遇到具体不支持的格式时说明缺口，不绕过工具边界。
- 使用内置 `Title`、`Heading1`、`Heading2` 层级，不另建自定义样式。用户指定中文字体时，在首次批量写入中为对应段落设置 `font.ea` 和字号。
- 简单表格在首次批量写入中一次给出全部行列、`light1` 样式和可见边框。普通首行写入表头文字即可，不设置重复表头属性，也不逐格回读和补格式。
- MCP 调用以 `command` 数组传操作，DOCX 和 JSON 操作文件都用本轮工作目录的绝对路径，例如 `{"command":["batch","/absolute/path/file.docx","--input","/absolute/path/ops.json"]}`；不要因相对路径找不到文件而转用 shell。

## 批量写入

- 不要先创建空文档再查看或调整。新稿必须一次性批量写入：准备好全文和完整 JSON 后，只创建一次，再用一次 `batch` 写入页面设置、全部段落和表格；不逐段、逐单元格调用 `set`。页码仅在用户或模板要求时写入。
- `batch` 接收 JSON 数组，每项的 `command` 是单个动词，其他参数与 `command` 同级。常见项如下：

```json
[
  {"command":"set","path":"/","props":{"pageWidth":"21cm","pageHeight":"29.7cm","marginTop":"2.5cm","marginBottom":"2.5cm","marginLeft":"2.5cm","marginRight":"2.5cm"}},
  {"command":"add","parent":"/body","type":"paragraph","props":{"text":"标题","style":"Title"}},
  {"command":"add","parent":"/body","type":"paragraph","props":{"text":"正文段落","style":"Normal"}},
  {"command":"add","parent":"/body","type":"table","props":{"data":"环节,内容,时长;1,操作演示,40分钟;2,课件练习,50分钟","style":"light1","border.all":"single;1pt;000000"}}
]
```

- 页型、边距、字体和标题层级服从用户要求或所选模板；没有明确要求时采用简洁、可读的默认值。只有缺少具体命令用法时才查对应帮助，查到后复用，不逐项查完整帮助。

## 一次核验

- 首次批量写入后，各调用一次 `view text` 和 `outline`，检查正文、标题层级及表格结构；不要对空文件查看结构，也不要逐段 `get`。
- 保存并 `close` 后渲染一次到新目录。对实际生成的 PDF 调用 `read_pdf`，设置 `limit=20`、`render=true`，再按工具返回的实际图片路径逐页检查全部页面。
- 只有发现事实/内容错误、缺文、结构错误或页面上可见的实质缺陷时才修订。将同类问题合并为一次 `batch`，然后再渲染并完整复核一次；不要删除并重建文档，也不要通过脚本修复 DOCX XML。没有可见的实质缺陷就直接交付，不做排版微调循环。
