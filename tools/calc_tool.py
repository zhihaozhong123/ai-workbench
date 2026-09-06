"""
计算器工具 - 执行数学表达式计算
"""
import ast
import operator
from langchain_core.tools import tool


# 安全的数学运算（禁止任意代码执行）
_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Mod: operator.mod,
}

_ALLOWED_NAMES = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": pow,
    "int": int,
    "float": float,
}


def _safe_eval(expr: str) -> float:
    """安全地计算数学表达式"""
    tree = ast.parse(expr.strip(), mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        elif isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in _ALLOWED_OPS:
                raise ValueError(f"不允许的运算符: {op_type.__name__}")
            return _ALLOWED_OPS[op_type](_eval(node.left), _eval(node.right))
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in _ALLOWED_OPS:
                raise ValueError(f"不允许的运算符: {op_type.__name__}")
            return _ALLOWED_OPS[op_type](_eval(node.operand))
        elif isinstance(node, ast.Name):
            if node.id not in _ALLOWED_NAMES:
                raise ValueError(f"不允许的函数: {node.id}")
            return _ALLOWED_NAMES[node.id]
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("不支持嵌套函数调用")
            if node.func.id not in _ALLOWED_NAMES:
                raise ValueError(f"不允许的函数: {node.func.id}")
            args = [_eval(arg) for arg in node.args]
            return _ALLOWED_NAMES[node.func.id](*args)
        else:
            raise ValueError(f"不支持的表达式类型: {type(node).__name__}")

    return _eval(tree)


@tool
def calculator(expression: str) -> str:
    """执行数学计算。支持加减乘除、幂运算、取模，以及 abs/round/min/max/sum/pow/int/float 等函数。
    参数 expression: 数学表达式，例如 '2 + 3 * 4' 或 '(100 + 200) / 3'。
    """
    try:
        result = _safe_eval(expression.strip())
        if isinstance(result, float) and result == int(result):
            result = int(result)
        return f"计算结果: {expression} = {result}"
    except Exception as e:
        return f"[ERROR] 计算错误: {str(e)}"
