"""專案慣例的檢查：機械性的規則寫成測試，不靠 review 時記得。

每條失敗時都寫明違反了什麼、該怎麼改。仍需要判斷的規範留在 CODING_STANDARDS.md；
前端「不用 localStorage.setItem」的規則在 frontend/eslint.config.js（no-restricted-syntax）。
檢查讀的是原始碼的語法樹（ast），不執行程式，所以註解與字串裡提到的名稱不算。
"""
import ast
import functools
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
API = BACKEND / "app" / "api"
RUNTIME = BACKEND / "app" / "runtime"


def _backend_files() -> list[Path]:
    """後端的程式：backend/app/ 底下與 backend/main.py；backend/.venv 不在範圍內。"""
    return [*sorted((BACKEND / "app").rglob("*.py")), BACKEND / "main.py"]


@functools.cache
def _tree(path: Path) -> ast.Module:
    # 給 bytes，由 Python 依 PEP 263 自己判斷編碼：CI 的 Windows 腿預設用系統碼頁
    return ast.parse(path.read_bytes(), filename=str(path))


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _module_name(path: Path) -> str:
    """backend/app/api/batch.py → app.api.batch；套件的 __init__.py 就是套件本身。"""
    parts = path.relative_to(BACKEND).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


# 一個 import 敘述：行號、所在的函式（模組層級是 None）、它載入的模組
_ImportStatement = tuple[int, str | None, list[str]]


def _imports(path: Path) -> Iterator[_ImportStatement]:
    """每個 import 敘述的行號、所在的函式（模組層級是 None）與它載入的模組。

    函式裡延遲的 import 也算。相對 import 換成完整名稱；``from X import Y`` 的 Y 可能是
    子模組，所以 X 與 X.Y 都列。
    """
    module = _module_name(path).split(".")
    package = module if path.name == "__init__.py" else module[:-1]

    def visit(node: ast.AST, function: str | None) -> Iterator[_ImportStatement]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Import):
                yield child.lineno, function, [alias.name for alias in child.names]
            elif isinstance(child, ast.ImportFrom):
                if child.level:
                    anchor = package[:len(package) - child.level + 1]
                    base = ".".join([*anchor, child.module] if child.module else anchor)
                else:
                    base = child.module or ""
                yield (child.lineno, function,
                       [base, *(f"{base}.{alias.name}" for alias in child.names)])
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from visit(child, child.name)
            else:
                yield from visit(child, function)

    yield from visit(_tree(path), None)


def _matching_nodes(files: list[Path], predicate: Callable[[ast.AST], bool]) -> list[str]:
    """這些檔案裡符合條件的語法節點，每個一行：「路徑:行號  原始碼」。"""
    return sorted({
        f"  {_rel(path)}:{node.lineno}  {ast.unparse(node)}"
        for path in files
        for node in ast.walk(_tree(path))
        if predicate(node)})


# ── 上傳檔名 ────────────────────────────────────────────────────────────

# api 裡指向 temp_uploads 的寫法：模組常數 TEMP_UPLOADS_DIR，或設定的屬性
_UPLOADS_DIR_NAMES = frozenset({"TEMP_UPLOADS_DIR"})
_UPLOADS_DIR_ATTRS = frozenset({"temp_uploads_path", "temp_uploads_dir"})


def _mentions_uploads_dir(node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id in _UPLOADS_DIR_NAMES
        or isinstance(n, ast.Attribute) and n.attr in _UPLOADS_DIR_ATTRS
        for n in ast.walk(node))


def _joined_parts(node: ast.AST) -> list[ast.expr]:
    """把路徑接起來的運算裡被接起來的各段；不是這種運算時回傳空串列。

    只看 ``/``、``os.path.join``、``joinpath`` 與 ``Path(a, b)``：f-string 與 ``+`` 常用在
    log 訊息，算進來會誤判。經過別名或 helper 參數的拼接也看不到，靠 review。
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return [node.left, node.right]                 # base / name
    if not isinstance(node, ast.Call):
        return []
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "joinpath":
        return [func.value, *node.args]                # base.joinpath(name)
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name in ("join", "Path", "PurePath"):
        return list(node.args)                         # os.path.join(base, name)、Path(base, name)
    return []


def _joins_uploads_dir_with_a_name(node: ast.AST) -> bool:
    """temp_uploads 和寫死的字串以外的東西接成路徑；寫死的子資料夾名稱不是前端送來的檔名。"""
    parts = _joined_parts(node)
    return any(
        _mentions_uploads_dir(part)
        and any(not (isinstance(other, ast.Constant) and isinstance(other.value, str))
                for other in parts[:i] + parts[i + 1:])
        for i, part in enumerate(parts))


def test_api_joins_upload_filenames_only_through_resolve_upload_path():
    files = sorted(API.rglob("*.py"))
    assert files, f"{_rel(API)} 底下沒有程式：api 搬家的話，跟著改這個測試的 API"
    violations = _matching_nodes(files, _joins_uploads_dir_with_a_name)
    assert not violations, (
        "api 把 temp_uploads 的路徑直接和檔名接起來：\n" + "\n".join(violations) + "\n"
        "前端送來的檔名帶 `..` 或絕對路徑時，接出來的路徑會指到 temp_uploads 外面，"
        "請求就能讀到、刪到使用者其他的檔案，包括音檔。改用 backend/app/utils/paths.py 的 "
        "resolve_upload_path(filename, TEMP_UPLOADS_DIR)：它只接受單純檔名，並保留 Docker 模式"
        "的 GPU worker 共用上傳檔所需的相對路徑。")


# ── 兩種執行模式 ────────────────────────────────────────────────────────

# 免安裝版沒有安裝這些套件（backend/requirements-standalone.txt 開頭的排除清單），
# CI 與開發環境卻都有裝：免安裝模式載入了它們，跑測試也不會失敗，只能靠這裡檢查
DOCKER_ONLY_PACKAGES = frozenset({"celery", "redis", "psycopg2", "gevent"})

# 只在 Docker 模式載入的模組：Celery 的 app 與任務，以及執行模式的 Celery＋Redis 轉接器。
# 只有它們可以 import 上面的套件與彼此；其他模組在免安裝模式都可能被載入。
# 要加進來之前，先確認免安裝模式不會載入它
DOCKER_ONLY_MODULES = frozenset({
    "app.celery.celery",
    "app.celery.task",
    "app.celery.batch_task",
    "app.runtime.celery_redis",
})

# 唯一的例外（import 它的模組、所在的函式、被 import 的模組）：run_mode.select() 依執行模式
# 選轉接器，只有 Docker 模式才走到這個延遲的 import；搬到模組層級，免安裝模式一載入就失敗
ALLOWED_DOCKER_ONLY_IMPORT = ("app.runtime.run_mode", "select", "app.runtime.celery_redis")


def _is_forbidden_import(importer: str, function: str | None, name: str) -> bool:
    """免安裝模式也會載入的模組（importer）裡，這個 import 是否會載入 Docker 模式專用的程式。"""
    if name.partition(".")[0] in DOCKER_ONLY_PACKAGES:
        return True
    return name in DOCKER_ONLY_MODULES and (importer, function, name) != ALLOWED_DOCKER_ONLY_IMPORT


def test_standalone_mode_never_imports_docker_only_code():
    violations = []
    for path in _backend_files():
        importer = _module_name(path)
        if importer in DOCKER_ONLY_MODULES:
            continue
        for lineno, function, names in _imports(path):
            hits = [name for name in names if _is_forbidden_import(importer, function, name)]
            if hits:
                violations.append(f"  {_rel(path)}:{lineno}  {hits[0]}")
    assert not violations, (
        "免安裝模式也會載入的模組 import 了 Docker 模式專用的套件或模組：\n"
        + "\n".join(sorted(violations)) + "\n"
        f"免安裝版沒有安裝 {'、'.join(sorted(DOCKER_ONLY_PACKAGES))}，一 import 就失敗；"
        "CI 有裝這些套件，跑測試看不出來。派送、撤銷、狀態廣播與取消旗標都經執行模式的介面"
        "（backend/app/runtime/run_mode.py 的 RunMode，用 run_mode.get() 取得）；要加功能時加進 "
        "RunMode，CeleryRedisRunMode 用這些套件實作，InProcessRunMode 用行程內的替代實作。"
        "確定這個模組只在 Docker 模式載入時，才把它加進這個測試的 DOCKER_ONLY_MODULES。")


def _celery_tasks() -> dict[str, str]:
    """以 @celery_app.task 註冊的 Celery 任務：函式名稱 → 所在檔案。"""
    def is_task_decorator(node: ast.expr) -> bool:
        target = node.func if isinstance(node, ast.Call) else node
        return isinstance(target, ast.Attribute) and target.attr == "task"

    return {
        node.name: _rel(path)
        for path in _backend_files()
        for node in ast.walk(_tree(path))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(is_task_decorator(decorator) for decorator in node.decorator_list)}


def _methods(path: Path, class_name: str) -> dict[str, ast.AST]:
    """class 裡定義的方法：名稱 → 函式。"""
    for node in _tree(path).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {item.name: item for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
    pytest.fail(f"{_rel(path)} 裡找不到 class {class_name}：搬家或改名的話，跟著改這個測試")


def _names_used(function: ast.AST) -> set[str]:
    """函式裡用到的名稱，含函式裡 import 進來的名稱。"""
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.alias):
            names.add(node.name.rpartition(".")[2])
    return names


def test_every_celery_task_can_be_dispatched_in_both_run_modes():
    tasks = _celery_tasks()
    assert tasks, ("找不到任何 @celery_app.task：任務的註冊方式改了的話，"
                   "跟著改這個測試的 _celery_tasks()")
    interface_methods = _methods(RUNTIME / "run_mode.py", "RunMode")
    celery_redis_methods = _methods(RUNTIME / "celery_redis.py", "CeleryRedisRunMode")
    in_process_methods = _methods(RUNTIME / "in_process.py", "InProcessRunMode")
    problems = []
    for task, where in sorted(tasks.items()):
        senders = sorted(name for name, method in celery_redis_methods.items()
                         if task in _names_used(method))
        if not senders:
            problems.append(f"  {task}（{where}）：CeleryRedisRunMode 沒有任何方法派送它")
        for name in senders:
            if name not in interface_methods:
                problems.append(f"  {task}：派送它的 CeleryRedisRunMode.{name} 不在 RunMode 介面裡")
            if name not in in_process_methods:
                problems.append(f"  {task}：InProcessRunMode 沒有 {name}，免安裝模式派送不了")
    assert not problems, (
        "Docker 模式的每個 Celery 任務，在免安裝模式都要有行程內的對應：\n"
        + "\n".join(problems) + "\n"
        "在執行模式的介面（backend/app/runtime/run_mode.py 的 RunMode）加一個 submit_… 方法："
        "CeleryRedisRunMode 用它派送這個 Celery 任務，InProcessRunMode 用執行緒池跑同一個任務本體。"
        "任務本體放 backend/app/tasks/，Celery 任務只轉呼叫它；API 一律經 run_mode.get() 派送。")


# ── 時間戳 ──────────────────────────────────────────────────────────────

# 由資料庫產生「現在時間」的 SQL 函式
DB_CLOCK_FUNCTIONS = frozenset({"now", "current_timestamp", "localtimestamp"})


def _is_db_clock(node: ast.AST) -> bool:
    """SQLAlchemy 的 func.now、sa.func.current_timestamp 這類寫法。"""
    if not (isinstance(node, ast.Attribute) and node.attr in DB_CLOCK_FUNCTIONS):
        return False
    owner = node.value
    return (isinstance(owner, ast.Name) and owner.id == "func"
            or isinstance(owner, ast.Attribute) and owner.attr == "func")


def test_timestamps_are_generated_in_python_not_by_the_database():
    violations = _matching_nodes(_backend_files(), _is_db_clock)
    assert not violations, (
        "時間戳要在 Python 端產生，不用資料庫的時間函式：\n" + "\n".join(violations) + "\n"
        "Postgres 容器與免安裝版的 SQLite 對 CURRENT_TIMESTAMP 的時區處理不同（SQLite 一律是 "
        "UTC），和 Python 端寫入、比較用的本地時間會差好幾個小時。欄位預設值用 "
        "default=datetime.now、onupdate=datetime.now（見 backend/app/database/models.py 的 "
        "ModelConfiguration.last_updated），查詢時也拿 datetime.now() 比較。")
