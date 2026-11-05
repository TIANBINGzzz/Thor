"""SQLGlot validates the complete query tree, including CTEs and subqueries."""

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

from .context import DataError

TENANT_PARAMETER = '_tenant_scope'


def _physical_tables(tree):
    """核对全部表节点均被作用域解析，不能遗漏分组 JOIN 中的根表。"""
    physical = []
    seen = set()
    for scope in traverse_scope(tree):
        for node, source in scope.selected_sources.values():
            if isinstance(source, exp.Table):
                if id(source) not in seen:
                    physical.append(source)
                seen.add(id(source))
            elif isinstance(node, exp.Table) and source is scope.cte_sources.get(node.name):
                seen.add(id(node))  # 已解析的 CTE 引用不是物理表。
    if any(id(table) not in seen for table in tree.find_all(exp.Table)):
        raise DataError('SQL_INVALID')
    return physical


def bind_tenant(tree, policy):
    """先过滤每个物理表再执行原查询，覆盖 JOIN、CTE、子查询和 UNION。"""
    tree = tree.copy()
    physical = _physical_tables(tree)
    # 从内向外改写；分组 JOIN 保留在表过滤之后，避免复制未约束的子表。
    for table in sorted(physical, key=lambda node: node.depth, reverse=True):
        column = policy['tenant_column']
        if column not in policy['tables'].get(table.name, {}):
            raise DataError('TENANT_SCOPE_NOT_ENFORCED')
        inner = table.copy()
        inner.set('alias', None)
        inner.set('joins', None)
        filtered = exp.select('*').from_(inner).where(
            exp.EQ(this=exp.column(column), expression=exp.Placeholder(this=TENANT_PARAMETER)))
        replacement = filtered.subquery(table.alias_or_name)
        if table.args.get('alias'):
            replacement.set('alias', table.args['alias'].copy())
        if table.args.get('joins'):
            replacement.set('joins', table.args['joins'])
        table.replace(replacement)
    return tree.sql(dialect='mysql'), bool(physical)


def validate_sql(sql, policy, *, dynamic=False):
    """校验完整只读查询树，限制表、函数及动态查询的内部列输出。"""
    if not isinstance(sql, str) or len(sql) > 60_000:
        raise DataError("SQL_INVALID")
    if "/*!" in sql or "/*M!" in sql.upper():
        raise DataError("SQL_READONLY_REQUIRED")
    try:
        statements = sqlglot.parse(sql, read="mysql")
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
            raise DataError("SQL_READONLY_REQUIRED")
        tree = statements[0]
        if dynamic and any(not isinstance(star.parent, exp.Count) for star in tree.find_all(exp.Star)):
            raise DataError("SQL_EXPLICIT_COLUMNS_REQUIRED")
        forbidden = (exp.DDL, exp.DML, exp.Command, exp.Into, exp.Lock, exp.Var,
                     exp.Parameter, exp.SessionParameter)
        if any(isinstance(node, forbidden) for node in tree.walk()):
            raise DataError("SQL_READONLY_REQUIRED")
        if any(node.args.get("recursive") for node in tree.find_all(exp.With)):
            raise DataError("SQL_RECURSION_FORBIDDEN")
        schema = policy.get("tables", {})
        for source in _physical_tables(tree):
            if source.db or source.catalog or source.name not in schema:
                raise DataError("TABLE_FORBIDDEN")
        functions = set(policy.get("functions", []))
        for node in tree.find_all(exp.Func):
            if isinstance(node, (exp.And, exp.Or, exp.Exists)):
                continue
            name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name()
            if name not in functions:
                raise DataError("FUNCTION_FORBIDDEN")
        qualified = qualify(tree.copy(), dialect="mysql", schema=schema,
                            validate_qualify_columns=True, quote_identifiers=False)
        if dynamic:
            # Model SQL can aggregate internal keys, but cannot return their
            # values, even hidden behind a CTE or expression alias.
            from sqlglot.lineage import lineage
            for selection in qualified.selects:
                graph = lineage(selection.alias_or_name, qualified, dialect="mysql", schema=schema)
                for node in graph.walk():
                    if not node.downstream:
                        column = node.name.rsplit(".", 1)[-1].strip('`"')
                        if column in policy.get("internal_columns", []):
                            raise DataError("INTERNAL_COLUMN_FORBIDDEN")
        return tree
    except DataError:
        raise
    except Exception:
        raise DataError("SQL_INVALID") from None
