# OfficeCLI Word撰写与核验

适用于创建或修改 DOCX。新稿应先完成全文和整批 JSON 操作，再开始编辑；已有文档只做本轮要求的修改，不重建原件。

本轮 DOCX 的完整操作规则在本文，已注入的必载 Skill 无需再搜索或读取。正文/大纲检查及 LibreOffice/PDFium 全页核验是 DOCX 的交付检查；Excel、幻灯片才按需加载对应原生 Skill。

`mcp__office__officecli` 的 `command` 是参数数组，例如 `{"command":["create","/absolute/path/article.docx"]}`。最短新稿链路：准备全文与格式 JSON → `create` → `batch`（写入及正文/大纲/表格回读）→ `close`（保存并释放文件）→ `mcp__documents__render` → 查看返回的页面图片及最终 DOCX 大纲。编辑、查询可以在内存中进行，不必每次操作后 `save`；外部渲染前必须先 `close`。有结果依赖的步骤依次执行，无需依赖新结果的多项操作集中在同一次调用。

普通文章默认只用内置标题层级，不添加封面、目录、页眉页脚或页码；用户明确要求或所选模板包含时才添加。模板和超长报告遵循其结构要求。

## 中文文稿默认格式

用户要求或所选模板优先；没有指定格式时，普通文章采用下面的论文式版面。公文与论文按文种选择，不混用字号体系；高校有各自规范，不能将通用默认值称为某校的正式模板。

| 项目 | 普通文章及论文式版面 | 明确要求公文时 |
| --- | --- | --- |
| 页面 | A4，上下左右边距 2.5cm | A4，上 3.7cm、下 3.5cm、左 2.8cm、右 2.6cm |
| 主标题 | `Title`，黑体三号 16pt，居中，段后 12pt | `Title`，方正小标宋简体二号 22pt，居中；环境无该字体时用黑体并说明替代 |
| 一级标题 | `Heading1`，黑体四号 14pt，左对齐，段前 12pt、段后 6pt | `Heading1`，黑体三号 16pt |
| 二级标题 | `Heading2`，黑体小四 12pt，左对齐，段前 6pt、段后 6pt | `Heading2`，楷体三号 16pt |
| 正文 | 宋体小四 12pt，英文/数字 Times New Roman，1.5 倍行距，首行缩进 24pt（2 字），段前后 0pt | 仿宋三号 16pt，固定行距 28pt，首行缩进 32pt（2 字），段前后 0pt |

所有标题和正文段落都在首次写入时显式设置 `color:"000000"`；标题层级只负责结构，不能依赖 `Title/Heading1/Heading2` 的主题字体、蓝色或装饰线。表格使用黑色边框和简洁样式。默认不用彩色标题、灰色副标题、下划线和装饰性横线。正文默认左对齐，用户或模板要求时才改两端对齐；参考文献及长 URL 用左对齐，保留完整链接。字体是否可用以实际渲染为准，不为选字体遍历宿主机。

## 工具边界

- 文档创建和修改必须通过 `mcp__office__officecli` MCP 完成。不要通过 Bash 或 shell 直接调用 `officecli`，不要用脚本读写 DOCX XML；文件交付确需复制时可使用已有发布流程。
- 普通撰写不加载完整 Word Skill（例如 `load_skill word`），也不探测系统字体、遍历工作目录或重复读取完整帮助。缺少具体命令语法时，只查一次对应的 OfficeCLI MCP 帮助。
- 普通撰写不编写 Python-docx 或 docx-js 临时文档生成器，也不通过脚本修复 OfficeCLI 产物；遇到具体不支持的格式时说明缺口，不绕过工具边界。
- 使用内置 `Title`、`Heading1`、`Heading2` 层级，不另建自定义样式。在首次批量写入中为对应段落设置 `font.ea`、`font.latin`、`size` 和黑色；这些直接格式覆盖内置样式的外观。
- 简单表格在首次批量写入中一次给出全部行列、`light1` 样式和可见边框。普通首行写入表头文字即可，不设置重复表头属性，也不逐格回读和补格式。
- MCP 调用以 `command` 数组传操作，DOCX 和 JSON 操作文件都用本轮工作目录的绝对路径。短稿直接 `{"command":["batch","/absolute/path/file.docx","--commands","[JSON操作数组]"]}`；长稿用 `--input` 读取已准备好的 JSON 文件。不要因相对路径找不到文件而转用 shell。

## 批量写入

- 不要先创建空文档再查看或调整。新稿必须一次性批量写入：准备好全文和完整 JSON 后，只创建一次，再用一次 `batch` 写入页面设置、全部段落和表格；不逐段、逐单元格调用 `set`。页码仅在用户或模板要求时写入。
- `batch` 接收 JSON 数组，每项的 `command` 是单个动词，其他参数与 `command` 同级。常见项如下：
- 新建空白文档时，在同一批次中先创建实际使用的 `Title`、`Heading1` 等段落样式，再添加正文；仅在段落填写 `style:"Heading1"` 不会可靠创建样式定义，LibreOffice 导出可能将其降为普通段落。一级标题样式须设置 `outlineLvl:0`，二级为 `1`，依次递增；已有模板复用其样式，不重复创建同名 ID。

```json
[
  {"command":"set","path":"/","props":{"pageWidth":"21cm","pageHeight":"29.7cm","marginTop":"2.5cm","marginBottom":"2.5cm","marginLeft":"2.5cm","marginRight":"2.5cm"}},
  {"command":"add","parent":"/styles","type":"style","props":{"id":"Title","name":"Title","type":"paragraph","basedOn":"Normal","font.ea":"黑体","size":"16pt","color":"000000","align":"center","spaceAfter":"12pt"}},
  {"command":"add","parent":"/styles","type":"style","props":{"id":"Heading1","name":"heading 1","type":"paragraph","basedOn":"Normal","next":"Normal","outlineLvl":0,"keepNext":true,"font.ea":"黑体","size":"14pt","color":"000000","spaceBefore":"12pt","spaceAfter":"6pt"}},
  {"command":"add","parent":"/body","type":"paragraph","props":{"text":"标题","style":"Title","font.ea":"黑体","font.latin":"Times New Roman","size":"16pt","color":"000000","align":"center","spaceAfter":"12pt"}},
  {"command":"add","parent":"/body","type":"paragraph","props":{"text":"章节标题","style":"Heading1","font.ea":"黑体","font.latin":"Times New Roman","size":"14pt","color":"000000","align":"left","spaceBefore":"12pt","spaceAfter":"6pt"}},
  {"command":"add","parent":"/body","type":"paragraph","props":{"text":"完整正文段落","style":"Normal","font.ea":"宋体","font.latin":"Times New Roman","size":"12pt","color":"000000","align":"left","lineSpacing":"1.5x","firstLineIndent":"24pt","spaceBefore":"0pt","spaceAfter":"0pt"}},
  {"command":"add","parent":"/body","type":"table","props":{"data":"环节,内容,时长;1,操作演示,40分钟;2,课件练习,50分钟","style":"light1","border.all":"single;1pt;000000"}},
  {"command":"view","mode":"text"},
  {"command":"view","mode":"outline"},
  {"command":"query","selector":"cell"}
]
```

- 页型、边距、字体和标题层级服从用户要求或所选模板；没有明确要求时采用简洁、可读的默认值。只有缺少具体命令用法时才查对应帮助，查到后复用，不逐项查完整帮助。
- 上例的段前、段后和行距可直接用于普通文章，在首次 `add` 时一起给出；中文字体用 `font.ea`，字号用 `size`。首行缩进使用 `firstLineIndent` 的长度值（正文两字为字号的两倍），不要使用 `firstLineChars`：当前 LibreOffice 渲染会丢失该字符单位缩进。不要先写无格式正文，再遍历段落补齐这些已知属性；不靠空段落制造间距。具体属性不确定时用 `{"command":["help","docx","paragraph"]}` 查询一次。
- 首次全文的事实、结构和字数自检在创建前集中完成；需要计算时一次计算全部指标。使用内联 `--commands` 无需生成操作文件；使用文件时，`Write` 必须先成功，后续才能 `batch --input` 读取，不能并行执行这两步。

## 一次核验

- 将 `view text`、`view outline` 以及需要的表格回读接在首次 `batch` 末尾，利用同次返回检查正文、标题层级及表格结构；无需再分开调用相同查询，不对空文件查看结构，不逐段 `get`。
- `close` 后渲染一次到新目录。`render` 返回的 `preview` 已含前20页文字、尺寸和实际页面图片路径，直接读取图片检查全部页面；若 `nextStart` 非空，再用 `read_pdf` 的 `start=nextStart`、`limit=20`、`render=true` 继续直到全页完成。互不依赖的图片读取可在同一轮发起。该检查已经覆盖分页，无需重复读取同一 PDF 或逐页 OfficeCLI 截图。渲染失败时报告具体障碍，不能以工具调用成功代替版式验收。
- 只有发现事实/内容错误、缺文、结构错误或页面上可见的实质缺陷时才修订。将同类问题合并为一次 `batch`，然后再渲染并完整复核一次；不要删除并重建文档，也不要通过脚本修复 DOCX XML。没有可见的实质缺陷就直接交付，不做排版微调循环。
- 中英文标点混排提示、字形完整且仍在页边距内的行尾标点悬挂，不构成内容或版式失败。不要为这些提示切换对齐方式、裁图放大或反复调整字距；`view issues` 的启发式建议不能代替实际页面判断。样式定义缺失及标题层级丢失属于结构错误，须补齐；对渲染后的 `docxPath` 用 `{"command":["view","/absolute/path/file.updated.docx","outline"]}` 查看一次大纲，确认标题层级保留后交付。`outline` 是位置参数，无需先 `open`，仅读取后无需 `save` 或 `close`；发布此更新版 DOCX 和对应 PDF，避免交付渲染前旧稿。
