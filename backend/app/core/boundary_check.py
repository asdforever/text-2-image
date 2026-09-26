"""路由层架构边界的静态检查。"""

import ast


_FORBIDDEN_IMPORT_ROOTS = {"sqlalchemy", "minio"}
_FORBIDDEN_STATE_ATTRIBUTES = {"db_session", "asset_storage"}
_FORBIDDEN_ADAPTER_CALLS = {
    "delete_directory",
    "delete_file",
    "generate_presigned_url",
    "put_object",
    "remove_object",
    "upload_asset_image",
    "upload_product",
    "upload_test_result",
}
_FORBIDDEN_CONSTRUCTORS = {
    "AsyncSession",
    "Session",
    "async_sessionmaker",
    "create_async_engine",
    "create_engine",
    "sessionmaker",
}


def find_route_boundary_violations(source: str, filename: str = "<route>") -> list[str]:
    """返回路由直接依赖数据库或对象存储适配器的位置。"""
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in _FORBIDDEN_IMPORT_ROOTS:
                    violations.append(
                        f"{filename}:{node.lineno} 禁止在路由导入 {root}"
                    )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in _FORBIDDEN_IMPORT_ROOTS:
                violations.append(
                    f"{filename}:{node.lineno} 禁止在路由导入 {root}"
                )
        elif isinstance(node, ast.Attribute):
            if node.attr in _FORBIDDEN_STATE_ATTRIBUTES:
                violations.append(
                    f"{filename}:{node.lineno} 禁止路由访问 {node.attr}"
                )
        elif isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in _FORBIDDEN_ADAPTER_CALLS | _FORBIDDEN_CONSTRUCTORS:
                violations.append(
                    f"{filename}:{node.lineno} 禁止路由直接调用 {name}"
                )

    return violations
