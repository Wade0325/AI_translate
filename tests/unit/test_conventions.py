"""專案慣例的檢查：機械性的規則寫成測試，不靠 review 時記得。

每條失敗時都寫明違反了什麼、該怎麼改。仍需要判斷的規範留在 CODING_STANDARDS.md；
前端「不用 localStorage.setItem」的規則在 frontend/eslint.config.js（no-restricted-syntax）。
檢查讀的是原始碼的語法樹（ast），不執行程式，所以註解與字串裡提到的名稱不算。
"""
import ast
import functools
import textwrap
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


# ── 回應不轉述例外 ──────────────────────────────────────────────────────

# 一個 except：所在檔案、函式（模組層級是 None）、接的例外（照原始碼的寫法）
_Handler = tuple[str, str | None, str]

# 訊息本來就寫給使用者看的例外類別：只接這些例外的 except 可以把例外放進回應。值是理由
USER_FACING_ERRORS = {
    "UnsafeUploadFilenameError":
        "訊息固定是 backend/app/utils/paths.py 的 UNSAFE_UPLOAD_FILENAME_MESSAGE，不帶檔名",
    "UnsupportedModelError":
        "訊息是 backend/app/provider/registry.py 寫的固定句子，只帶請求自己送來的供應商與模型名稱",
}

# 刻意把例外的原文放進回應的 except。值是理由
FORWARDING_HANDLERS: dict[_Handler, str] = {
    ("backend/app/api/model_manager.py", "check_provider_ready", "ValueError"):
        "設定頁的「測試」刻意把供應商回報的原因（例如金鑰無效、缺模型權重）給使用者看："
        "使用者按測試，就是要知道為什麼還不能轉錄",
}

_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log"})


def _is_log_call(node: ast.AST) -> bool:
    """寫進 log 的呼叫，例如 ``logger.error(…)``；api 的模組都用 setup_logger 建立 logger。"""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_METHODS
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger")


def _except_handlers(tree: ast.Module) -> Iterator[tuple[str | None, ast.ExceptHandler]]:
    """每個 except 與它所在的函式（模組層級是 None）。"""
    def visit(node: ast.AST, function: str | None
              ) -> Iterator[tuple[str | None, ast.ExceptHandler]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ExceptHandler):
                yield function, child
            yield from visit(child, child.name
                             if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                             else function)

    yield from visit(tree, None)


def _caught(handler: ast.ExceptHandler) -> list[str]:
    """except 接的例外類別：``except (A, errors.B)`` 是 A 與 B。"""
    if handler.type is None:
        return []
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return [t.attr if isinstance(t, ast.Attribute) else ast.unparse(t) for t in types]


def _statements_using_the_exception(handler: ast.ExceptHandler) -> set[ast.stmt]:
    """except 區塊裡把接到的例外用在 log 與 ``raise … from`` 以外的敘述。"""
    found: set[ast.stmt] = set()

    def visit(node: ast.AST, statement: ast.stmt) -> None:
        if isinstance(node, ast.stmt):
            statement = node
        if isinstance(node, ast.Name) and node.id == handler.name:
            found.add(statement)
        elif isinstance(node, ast.Raise):
            if node.exc:                    # from 後面只是接起來；丟出去的例外照樣檢查
                visit(node.exc, statement)
        elif not (_is_log_call(node)
                  # 裡層的 except 用同一個名稱接了別的例外：它自己另外檢查
                  or isinstance(node, ast.ExceptHandler) and node.name == handler.name):
            for child in ast.iter_child_nodes(node):
                visit(child, statement)

    for statement in handler.body:
        visit(statement, statement)
    return found


def _forwarded_exceptions(rel: str, tree: ast.Module) -> Iterator[tuple[_Handler, ast.stmt]]:
    """把接到的例外放進回應的敘述，連同那個 except 在 FORWARDING_HANDLERS 的鍵。

    接到的例外用在 log 與 ``raise … from`` 以外的地方都算：HTTP 的 detail、回傳的內容、
    WebSocket 的訊息，以及之後才回傳的狀態。只接 USER_FACING_ERRORS 的 except 不算。
    只看 except 用 as 接住的名稱：在 helper 裡接住、再把例外的文字傳回來的，靠 review。
    """
    for function, handler in _except_handlers(tree):
        if handler.name is None or handler.type is None:
            continue
        if all(name in USER_FACING_ERRORS for name in _caught(handler)):
            continue
        key = (rel, function, ast.unparse(handler.type))
        for statement in _statements_using_the_exception(handler):
            yield key, statement


def test_api_never_puts_caught_exceptions_in_responses():
    files = sorted(API.rglob("*.py"))
    assert files, f"{_rel(API)} 底下沒有程式：api 搬家的話，跟著改這個測試的 API"
    violations: set[str] = set()
    exempted: set[_Handler] = set()
    for path in files:
        for handler, statement in _forwarded_exceptions(_rel(path), _tree(path)):
            if handler in FORWARDING_HANDLERS:
                exempted.add(handler)
            else:
                violations.add(f"  {handler[0]}:{statement.lineno}  "
                               f"{ast.unparse(statement).splitlines()[0]}")
    assert not violations, (
        "api 把接到的例外放進了回應（HTTP 的 detail，或回傳、送給前端的內容）：\n"
        + "\n".join(sorted(violations)) + "\n"
        "例外的文字可能帶著明文 API 金鑰、SQL 參數（例如轉錄結果）或本機路徑；畫面上的錯誤"
        "會被截圖附到公開的 GitHub Issues（ADR-0005）。回應改成使用者看得懂的固定訊息，原因"
        "寫進 log（資料庫例外用 describe_db_error(e)），例外用 raise … from e 接起來。"
        "例外類別寫明訊息就是給使用者看的，才把它加進這個測試的 USER_FACING_ERRORS；刻意要"
        "給使用者看例外原文的 except，加進 FORWARDING_HANDLERS。兩者都要寫明理由。")
    stale = sorted(set(FORWARDING_HANDLERS) - exempted, key=str)
    assert not stale, (
        "FORWARDING_HANDLERS 裡的 except 找不到，或已經不轉述例外：\n"
        + "\n".join(f"  {path}  {function}()  except {caught}"
                    for path, function, caught in stale) + "\n"
        "已經不轉述例外的，從清單拿掉；搬了檔案、改了函式名稱或接的例外的，照新的寫。")


def _endpoint_catching(except_block: str) -> ast.Module:
    """把一段 except 接在 api 端點的 try 後面，解析成語法樹。"""
    return ast.parse("async def endpoint():\n    try:\n        await work()\n"
                     + textwrap.indent(textwrap.dedent(except_block), "    "))


@pytest.mark.parametrize("except_block", [
    pytest.param("""
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"存不進去：{e}") from e
        """, id="http-detail"),
    pytest.param("""
        except ValueError as e:
            return {"success": False, "message": str(e)}
        """, id="returned-content"),
    pytest.param("""
        except OSError as e:
            await websocket.send_json({"status_text": repr(e)})
        """, id="websocket-message"),
    pytest.param("""
        except Exception as e:
            _state.update(state="failed", error=str(e))
        """, id="state-returned-later"),
    pytest.param("""
        except Exception as e:
            message = describe_db_error(e)
            raise HTTPException(status_code=500, detail=message) from e
        """, id="log-description-in-response"),
    pytest.param("""
        except (UnsafeUploadFilenameError, OSError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        """, id="partly-user-facing"),
])
def test_forwarding_check_catches_each_way_into_a_response(except_block):
    assert list(_forwarded_exceptions("backend/app/api/example.py",
                                      _endpoint_catching(except_block)))


@pytest.mark.parametrize("except_block", [
    pytest.param("""
        except Exception as e:
            logger.error(f"存檔失敗: {describe_db_error(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail="設定沒有存進資料庫") from e
        """, id="log-and-raise-from"),
    pytest.param("""
        except UnsafeUploadFilenameError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        """, id="user-facing-error"),
    pytest.param("""
        except OSError:
            raise HTTPException(status_code=500, detail="檔案沒有存進去") from None
        """, id="not-bound"),
])
def test_forwarding_check_allows_logging_and_chaining(except_block):
    assert not list(_forwarded_exceptions("backend/app/api/example.py",
                                          _endpoint_catching(except_block)))


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
