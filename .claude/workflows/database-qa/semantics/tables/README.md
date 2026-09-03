# 表级语义文件

为需要稳定口径的表新增一个 Markdown 文件，文件名建议使用表名，例如：

```text
semantics/tables/t_hpm_project.md
```

每个文件只记录已核实的字段含义、主键/关联关系、状态值和常用过滤条件。
不要把密码、连接串、用户 Token 或未经验证的字段解释写入语义文件。

新增文件后，把相对路径加入 `workflow.json` 的 `documents.semantics` 数组，运行时才会加载它。
