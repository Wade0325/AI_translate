"""PreToolUse hook：擋下 AI 對受保護檔案的寫入、刪除與搬移。

受保護的檔案只由使用者本人修改：

  * ``lab/data/eval/`` 底下的檔 —— 使用者親手聽打的標準答案（包括 ``rec17.tsv``）。
    ``lab/`` 被 git 忽略，覆寫或刪除後沒有版控可以還原
  * ``.env`` 與 ``.env.*`` —— 環境變數與金鑰。``.env.example`` 是範本，不受保護

檢查 Edit、Write 的 ``file_path``，NotebookEdit 的 ``notebook_path``，以及 Bash、
PowerShell 的 ``command``。命令先依 shell 的規則切成字詞（引號、heredoc 與
here-string 裡的文字不當成指令），每個字詞正規化（``\\`` 換成 ``/``、轉小寫）後
再比對，只在寫入型動作指向受保護路徑時擋下：

  * ``>``、``>>`` 等重新導向的目標
  * ``Set-Content``、``Add-Content``、``Out-File``、``tee`` 寫入的檔
  * ``Copy-Item``／``cp`` 的目的地；``Move-Item``／``mv`` 的來源與目的地
  * ``Remove-Item``／``rm`` 刪除的路徑

PowerShell 的別名（``del``、``copy``…），以及經 ``xargs``、``find -exec``、
``bash -c``、``powershell -Command``、``cmd /c`` 執行的也算。目標是 ``lab``、
``lab/data``、``lab/data/eval`` 本身或它們底下的萬用字元時一樣擋：刪掉或搬走
上層，標準答案也跟著不見。沒有 ``-n``／``--dry-run`` 的 ``git clean`` 一律擋：
它刪的是被 git 忽略的檔，命令裡不會出現路徑。

只擋寫入，不擋讀取：``cat``、``Get-Content``、用 ``python`` 讀標準答案都放行。
讀不到 payload 或檢查時出錯就擋下（exit 2），不靜默放行。

擋不到的：Python 等子程序自己寫檔、用變數或迴圈組出來的路徑、上面沒列的寫檔
指令（例如 ``sed -i``、``Rename-Item``）。只用標準函式庫，不依賴後端的 venv。
"""

from __future__ import annotations

import fnmatch
import json
import sys

# Windows 的 stderr 用系統碼頁，中文理由會變亂碼，Claude 就看不懂為什麼被擋
try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── 保護範圍：比對正規化後的路徑拆成的各層 ─────────────────────────────

# 標準答案所在的資料夾。寫入它底下的檔（*/lab/data/eval/*），或對它本身與上層的
# lab、lab/data（含萬用字元，例如 lab/*）寫入、刪除、搬移，都擋下
EVAL_DIR = ("lab", "data", "eval")
EVAL_FILE_REASON = "lab/data/eval/ 底下是使用者親手聽打的標準答案，覆寫或刪除後沒有版控可以還原"
EVAL_PARENT_REASON = "它是標準答案所在的 lab/data/eval 或它的上層，寫入、刪除或搬移它會波及標準答案"

# .env 與它的變體（*/.env、*/.env.*）；.env.example 是範本，放行
ENV_PATTERNS = (".env", ".env.*")
ENV_TEMPLATE = ".env.example"
ENV_REASON = ".env 與它的變體存放環境變數與金鑰"
# 檔名是萬用字元時（例如 rm .env*），拿常見的變體試比對
ENV_PROBES = (".env", ".env.local", ".env.production", ".env.development", ".env.test")

GIT_CLEAN_REASON = (
    "沒有 -n／--dry-run 的 git clean 會刪掉被 git 忽略的檔，包括 lab/ 的標準答案與 .env，"
    "命令裡卻看不出會刪到哪些。先用 git clean -n 列出會刪的檔；真的要刪，請使用者自己執行"
)

POLICY = (
    "這個 hook 檢查編輯工具、notebook 與 Bash／PowerShell 命令，只擋寫入、刪除與搬移，"
    "不擋讀取：cat、Get-Content、用 python 讀都可以。"
    "標準答案與 .env 只由使用者本人修改：需要變更時，說明原因並請使用者自己改，"
    "或改寫到其他檔名；不要改用 python 或其他寫法繞過。"
)

# ── 寫入型動作 ───────────────────────────────────────────────────────

# 指令名稱已正規化、去掉路徑與 .exe；PowerShell 的別名一併列入
WRITE_ACTIONS = {
    "delete": ("rm", "rmdir", "remove-item", "ri", "del", "erase", "rd"),
    "move": ("mv", "move-item", "mi", "move"),
    "copy": ("cp", "copy-item", "cpi", "copy"),
    "content": ("set-content", "sc", "add-content", "ac", "out-file"),
    "tee": ("tee", "tee-object"),
}
_FAMILY = {verb: family for family, verbs in WRITE_ACTIONS.items() for verb in verbs}

# 這些名稱在 bash、cmd 裡是各自的原生指令，參數的寫法和 PowerShell 不同
_BASH_NATIVE = {"rm", "rmdir", "cp", "mv", "tee"}
_CMD_NATIVE = {"del", "erase", "rd", "rmdir", "copy", "move"}

_CD = {"cd", "chdir", "set-location", "sl", "pushd", "push-location"}

# 放在指令前面、本身不寫檔的包裝與關鍵字：跳過它們（和它們的選項）找真正的指令
_WRAPPERS = {
    "sudo", "env", "command", "builtin", "exec", "nohup", "time", "nice", "timeout",
    "stdbuf", "xargs", "do", "then", "else", "elif", "if", "while", "until", "!",
}
_WRAPPER_VALUED = {  # 包裝的選項裡，會吃掉下一個字詞的（區分大小寫）
    "sudo": {"-u", "-g"}, "env": {"-u"}, "nice": {"-n"}, "timeout": {"-s", "-k"},
    "xargs": {"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s"},
}

_POSIX_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
_POWERSHELLS = {"powershell", "pwsh"}
# powershell.exe 會吃掉下一個字詞的選項（-Command 之前的）
_POWERSHELL_EXE_VALUED = (
    "executionpolicy", "windowstyle", "inputformat", "outputformat", "version", "psconsolefile",
    "configurationname", "workingdirectory", "settingsfile", "custompipename",
)
_POWERSHELL_EXE_SHORT = {"ep", "ex", "w", "if", "of", "v", "wd"}

# ── PowerShell 的參數：帶值的會吃掉下一個字詞，其餘是開關 ─────────────────
_PS_PARAMS = {  # family: (帶值的參數, 開關)
    "delete": ({"path", "literalpath", "filter", "include", "exclude", "credential", "stream"},
               {"recurse", "force"}),
    "move": ({"path", "literalpath", "destination", "filter", "include", "exclude", "credential"},
             {"force", "passthru"}),
    "copy": ({"path", "literalpath", "destination", "filter", "include", "exclude", "credential",
              "fromsession", "tosession"},
             {"container", "force", "passthru", "recurse"}),
    "content": ({"path", "literalpath", "filepath", "value", "filter", "include", "exclude",
                 "credential", "encoding", "stream", "width", "inputobject"},
                {"passthru", "force", "nonewline", "append", "noclobber"}),
    "tee": ({"filepath", "literalpath", "variable", "inputobject", "encoding"}, {"append"}),
}
_PS_COMMON_VALUED = {
    "erroraction", "errorvariable", "warningaction", "warningvariable", "informationaction",
    "informationvariable", "outvariable", "outbuffer", "pipelinevariable",
}
_PS_COMMON_SWITCHES = {"verbose", "debug", "whatif", "confirm", "usetransaction"}
_PS_ALIASES = {
    "lp": "literalpath", "pspath": "literalpath", "ea": "erroraction", "ev": "errorvariable",
    "wa": "warningaction", "wv": "warningvariable", "infa": "informationaction",
    "iv": "informationvariable", "ov": "outvariable", "ob": "outbuffer", "pv": "pipelinevariable",
    "vb": "verbose", "db": "debug", "wi": "whatif", "cf": "confirm", "usetx": "usetransaction",
}
_PS_PATHS = ("path", "literalpath", "filepath")

_DIALECTS = {"Bash": ("bash",), "PowerShell": ("powershell",)}


# ── 路徑 ──────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    """路徑與指令名稱一律正規化後再比對：\\ 換成 /、轉小寫。"""
    return text.replace("\\", "/").lower()


def _parts(path: str) -> list[str]:
    """正規化後的路徑拆成各層，處理 . 與 ..。"""
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return parts


def _resolve(word: str, base: str) -> list[str]:
    """相對路徑接在 base（目前的資料夾）後面，再拆成各層。"""
    path = _norm(word)
    if not (path.startswith("/") or path[1:2] == ":"):
        path = f"{base}/{path}"
    return _parts(path)


def _is_env_name(name: str) -> bool:
    """.env 或它的變體（.env.local、.env.production…），.env.example 除外。"""
    if name == ENV_TEMPLATE:
        return False
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in ENV_PATTERNS):
        return True
    # rm .env* 這類萬用字元：以 . 開頭才涵蓋得到隱藏檔，rm * 不算
    return name.startswith(".") and any(fnmatch.fnmatchcase(probe, name) for probe in ENV_PROBES)


def _path_reason(parts: list[str]) -> str | None:
    """受保護的路徑回傳理由，否則回傳 None。各層可以是萬用字元（lab/*）。"""
    for i, part in enumerate(parts):
        if part != EVAL_DIR[0]:
            continue
        rest = parts[i + 1:]
        # 逐層比對 data、eval：比完還有剩是標準答案的檔，沒剩是 lab、lab/data 或 eval 本身
        # （rest 比較短時只比到 rest 的長度，所以 strict=False）
        pairs = zip(EVAL_DIR[1:], rest, strict=False)
        if all(fnmatch.fnmatchcase(want, got) for want, got in pairs):
            return EVAL_FILE_REASON if len(rest) >= len(EVAL_DIR) else EVAL_PARENT_REASON
    if parts and _is_env_name(parts[-1]):
        return ENV_REASON
    return None


def _brace_expand(word: str, limit: int = 64) -> list[str]:
    """bash 的 {a,b} 展開（不處理巢狀）。"""
    start = word.find("{")
    end = word.find("}", start + 1)
    if start < 0 or end < 0 or "," not in word[start + 1:end]:
        return [word]
    out: list[str] = []
    for choice in word[start + 1:end].split(","):
        out += _brace_expand(word[:start] + choice + word[end + 1:], limit)
        if len(out) >= limit:
            break
    return out[:limit]


def _candidates(word: str, groups: dict, depth: int = 0) -> list[str]:
    """一個字詞可能代表的路徑：展開 {a,b}、拆開逗號（PowerShell 的陣列），
    ( ) 的記號換成裡面的字詞，以及頭一段指令的參數接成的路徑（Join-Path $PWD 'lab'）。"""
    out: list[str] = []
    for piece in _brace_expand(word):
        for part in piece.split(","):
            if "\x00" not in part or depth > 3:
                if part:
                    out.append(part)
                continue
            for marker, (words, first) in groups.items():
                if marker in part:
                    out += _candidates(part.replace(marker, "/".join(first)), groups, depth + 1)
                    for inner in words:
                        out += _candidates(inner, groups, depth + 1)
    return out


# ── 切詞 ──────────────────────────────────────────────────────────────

class _Seg:
    """一段指令：字詞（已去掉引號，尚未正規化）與重新導向寫入的目標。"""

    __slots__ = ("words", "writes")

    def __init__(self, words: list[str] | None = None):
        self.words: list[str] = list(words or [])
        self.writes: list[str] = []


class _Lexer:
    """把命令切成敘述，每個敘述是一串指令片段。只求找出寫入的目標，不是完整的 shell 語法。

    * 引號與跳脫字元依 bash、PowerShell 或 cmd 的規則處理；heredoc 的內容略過、
      here-string 的內容當成一個字詞，都不會被當成指令
    * ;、&&、||、換行斷開敘述；| 與 ( )、{ } 只斷開片段，ForEach-Object { } 裡的
      $_ 才找得到管線上游
    * 參數位置的 ( )、$( )、@( ) 換成一個記號字詞，裡面的字詞記在 groups
    """

    def __init__(self, text: str, dialect: str):
        self.text = text.replace("\r\n", "\n")
        self.dialect = dialect
        self.pos = 0
        self.statements: list[list[_Seg]] = [[]]
        self.seg = _Seg()
        self.word: str | None = None    # 正在累積的字詞
        self.target: str | None = None  # 下一個字詞的去處：write（寫入的目標）、skip（丟掉）
        self.frames: list[tuple] = []   # 進入 ( ) 或 { } 前的狀態
        self.heredocs: list[tuple[str, bool]] = []
        self.groups: dict[str, tuple[list[str], list[str]]] = {}

    def run(self) -> list[list[_Seg]]:
        text = self.text
        while self.pos < len(text):
            c = text[self.pos]
            nxt = text[self.pos + 1:self.pos + 2]
            if c in " \t\r":
                self._end_word()
                self.pos += 1
            elif c == "\n":
                self.pos += 1
                self._end_statement()
                self._skip_heredocs()
            elif c == "#" and self.word is None and self.dialect != "cmd":
                end = text.find("\n", self.pos)        # 註解
                self.pos = len(text) if end < 0 else end
            elif c == "'" and self.dialect != "cmd":
                self._quoted("'")
            elif c == '"':
                self._quoted('"')
            elif (c, self.dialect) in (("\\", "bash"), ("`", "powershell"), ("^", "cmd")):
                if nxt not in ("", "\n"):              # 接換行是續行
                    self._append(nxt)
                self.pos += 2
            elif c == "@" and nxt in ("'", '"') and self.dialect == "powershell":
                if not self._here_string():
                    self._append(c)
                    self.pos += 1
            elif c == "$" and nxt == "{":
                end = text.find("}", self.pos)         # ${VAR}
                end = len(text) if end < 0 else end + 1
                self._append(text[self.pos:end])
                self.pos = end
            elif c in "$@<" and nxt == "(":
                self.pos += 1                          # $( )、@( )、<( )
                self._open("(", argument=True)
            elif c == "(":
                self._open("(", argument=self.word is not None or bool(self.seg.words))
            elif c == ")":
                self._close("(")
            elif c == "{" and nxt == "}":
                self._append("{}")                     # find -exec 的 {}
                self.pos += 2
            elif c == "{" and self.word is None:
                self._open("{", argument=False)        # script block、{ …; } 群組
            elif c == "}" and self._closes_block():
                self._close("{")
            elif c == ">" or (c in "&*" and nxt == ">") or (
                    c.isdigit() and self.word is None and nxt == ">"):
                self._redirect()
            elif c == "<":
                self._input()
            elif c in ";|&":
                self._operator()
            else:
                self._append(c)
                self.pos += 1
        while self.frames:
            self._close(self.frames[-1][0])
        self._end_segment()
        return [statement for statement in self.statements if statement]

    def _append(self, s: str) -> None:
        self.word = (self.word or "") + s

    def _end_word(self) -> None:
        if self.word is None:
            return
        if self.target == "write":
            self.seg.writes.append(self.word)
        elif self.target is None:
            self.seg.words.append(self.word)
        self.word, self.target = None, None

    def _end_segment(self) -> None:
        self._end_word()
        self.target = None
        if self.seg.words or self.seg.writes:
            self.statements[-1].append(self.seg)
        self.seg = _Seg()

    def _end_statement(self) -> None:
        self._end_segment()
        if not self.frames and self.statements[-1]:
            self.statements.append([])

    def _quoted(self, quote: str) -> None:
        text, i = self.text, self.pos + 1
        chars: list[str] = []
        while i < len(text):
            c, nxt = text[i], text[i + 1:i + 2]
            if c == quote:
                if self.dialect == "powershell" and nxt == quote:  # '' 或 "" 是引號本身
                    chars.append(quote)
                    i += 2
                    continue
                i += 1
                break
            if quote == '"' and (
                    (self.dialect == "bash" and c == "\\" and nxt in ('"', "\\", "$", "`", "\n"))
                    or (self.dialect == "powershell" and c == "`" and nxt)):
                if nxt != "\n":
                    chars.append(nxt)
                i += 2
                continue
            chars.append(c)
            i += 1
        self._append("".join(chars))
        self.pos = i

    def _here_string(self) -> bool:
        """PowerShell 的 @' … '@：內容整段當成一個字詞。"""
        text = self.text
        quote, start = text[self.pos + 1], self.pos + 2
        while text[start:start + 1] in (" ", "\t"):
            start += 1
        if text[start:start + 1] != "\n":
            return False
        end = text.find("\n" + quote + "@", start)
        self._append(text[start + 1:] if end < 0 else text[start + 1:end])
        self.pos = len(text) if end < 0 else end + 3
        return True

    def _redirect(self) -> None:
        text = self.text
        self._end_word()
        if text[self.pos] != ">":
            self.pos += 1                  # 2>、&>、*> 的前綴
        self.pos += 1
        if text[self.pos:self.pos + 1] == ">":
            self.pos += 1                  # >>
        if text[self.pos:self.pos + 1] in ("|", "&"):
            self.pos += 1                  # >|、2>&1
        self.target = "write"

    def _input(self) -> None:
        text = self.text
        if self.dialect == "powershell" and text.startswith("<#", self.pos):
            end = text.find("#>", self.pos + 2)        # <# … #> 註解
            self.pos = len(text) if end < 0 else end + 2
            return
        self._end_word()
        if self.dialect == "bash" and text.startswith("<<", self.pos) and not text.startswith("<<<", self.pos):
            self._heredoc()
            return
        self.pos += 3 if text.startswith("<<<", self.pos) else 1
        if text[self.pos:self.pos + 1] in (">", "&"):
            self.pos += 1                              # <>、<&3
        self.target = "skip"                           # 讀取的來源，不是寫入的目標

    def _heredoc(self) -> None:
        """bash 的 <<EOF：記下結束記號，內容在換行之後由 _skip_heredocs 略過。"""
        text = self.text
        self.pos += 2
        strip_tabs = text[self.pos:self.pos + 1] == "-"
        if strip_tabs:
            self.pos += 1
        while text[self.pos:self.pos + 1] in (" ", "\t"):
            self.pos += 1
        start = self.pos
        while self.pos < len(text) and text[self.pos] not in " \t\n;|&<>()":
            self.pos += 1
        delimiter = text[start:self.pos]
        for quote in ("'", '"', "\\"):                 # 'EOF'、"EOF"、\EOF
            delimiter = delimiter.replace(quote, "")
        if delimiter:
            self.heredocs.append((delimiter, strip_tabs))

    def _skip_heredocs(self) -> None:
        text = self.text
        for delimiter, strip_tabs in self.heredocs:
            while self.pos < len(text):
                end = text.find("\n", self.pos)
                line = text[self.pos:] if end < 0 else text[self.pos:end]
                self.pos = len(text) if end < 0 else end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                    break
        self.heredocs = []

    def _operator(self) -> None:
        text = self.text
        c, pair = text[self.pos], text[self.pos:self.pos + 2]
        if pair in ("&&", "||", ";;"):
            self.pos += 2
            self._end_statement()
        elif c == "|":
            self.pos += 2 if pair == "|&" else 1
            self._end_segment()                        # 管線：同一個敘述的下一段
        elif c == "&" and self.dialect == "powershell":
            self.pos += 1
            self._end_segment()                        # 呼叫運算子：& "C:\x.exe"
        else:
            self.pos += 1
            self._end_statement()                      # ;，以及 bash、cmd 的 &

    def _open(self, kind: str, argument: bool) -> None:
        self.pos += 1
        if argument:
            frame = (kind, self.seg, self.word, self.target, len(self.statements[-1]))
            self.seg, self.word, self.target = _Seg(), None, None
        else:
            self._end_segment()
            frame = (kind, None, None, None, len(self.statements[-1]))
        self.frames.append(frame)

    def _close(self, kind: str) -> None:
        self.pos += 1
        self._end_segment()
        if not self.frames or self.frames[-1][0] != kind:
            return                                     # 落單的右括號（例如 case 的樣式）
        _, outer, word, target, start = self.frames.pop()
        if outer is None:
            return
        # 參數位置的 ( )：裡面的字詞記下來，原處接上記號字詞
        inner = self.statements[-1][start:]
        marker = f"\x00{len(self.groups)}\x00"
        first = inner[0].words[1:] if inner else []
        self.groups[marker] = (
            [w for seg in inner for w in seg.words],
            [w for w in first if not w.startswith("-")],
        )
        self.seg, self.target = outer, target
        self.word = (word or "") + marker

    def _closes_block(self) -> bool:
        if not self.frames or self.frames[-1][0] != "{":
            return False
        # brace expansion（lab/{data,runs}）的 } 屬於字詞
        return self.word is None or self.word.count("{") <= self.word.count("}")


# ── 指令 ──────────────────────────────────────────────────────────────

def _command_name(word: str) -> str:
    """指令名稱：正規化，去掉路徑與 .exe 這類副檔名。"""
    name = _norm(word).rsplit("/", 1)[-1]
    for ext in (".exe", ".cmd", ".bat"):
        if name.endswith(ext):
            return name[:-len(ext)]
    return name


def _is_assignment(word: str) -> bool:
    """bash 的 NAME=value 前綴。"""
    name, eq, _ = word.partition("=")
    return bool(eq) and name.replace("_", "a").isalnum() and not name[:1].isdigit()


def _command_start(words: list[str]) -> tuple[int, bool]:
    """跳過環境變數設定與 sudo、env、xargs 這類包裝，回傳 (指令的位置, 是否經過 xargs)。"""
    i, via_xargs = 0, False
    while i < len(words):
        if _is_assignment(words[i]):
            i += 1
            continue
        name = _command_name(words[i])
        if name not in _WRAPPERS:
            break
        via_xargs = via_xargs or name == "xargs"
        valued = _WRAPPER_VALUED.get(name, set())
        i += 1
        while i < len(words) and (words[i].startswith("-") or _is_assignment(words[i])):
            i += 2 if words[i] in valued else 1
        if name == "timeout" and i < len(words):
            i += 1                                     # 時限
    return i, via_xargs


def _is_git_clean(args: list[str]) -> bool:
    """沒有 -n／--dry-run 的 git clean。git 的選項區分大小寫，用原始字詞比對。"""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        # 會吃掉下一個字詞的全域選項：-C <路徑>、-c <設定>…
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env") else 1
    if i >= len(args) or args[i].lower() != "clean":
        return False
    for arg in args[i + 1:]:
        if arg == "--":
            break
        if arg.startswith("--"):
            if len(arg) > 2 and "--dry-run".startswith(arg):
                return False
        elif arg.startswith("-") and "n" in arg[1:].split("e")[0]:
            return False                               # -n 或 -fdn 這類合寫；-e 之後是排除樣式
    return True


def _shell_command(args: list[str]) -> str | None:
    """bash -c 'cmd'、bash -lc 'cmd'：-c 之後第一個不是選項的字詞。"""
    seen_c, i = False, 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-") and not arg.startswith("--"):
            seen_c = seen_c or "c" in arg[1:]
            if arg in ("-o", "-O"):
                i += 1                                 # set -o 的值
        elif not arg.startswith("--"):
            return arg if seen_c else None             # 沒有 -c：執行腳本檔，看不到內容
        i += 1
    return None


def _powershell_command(args: list[str]) -> str | None:
    """powershell -Command …：之後的字詞都是命令。-File 與 -EncodedCommand 看不到內容。"""
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-"):
            return " ".join(args[i:])                  # 沒寫 -Command：其餘的字詞就是命令
        name = arg[1:].lower()
        if name in ("e", "ec") or (len(name) > 1 and "encodedcommand".startswith(name)) or (
                name and "file".startswith(name)):
            return None
        if "command".startswith(name):
            return " ".join(args[i + 1:])
        if name in _POWERSHELL_EXE_SHORT or (
                len(name) >= 3 and any(o.startswith(name) for o in _POWERSHELL_EXE_VALUED)):
            i += 1
        i += 1
    return None


def _nested_command(verb: str, args: list[str]) -> tuple[str, str] | None:
    """bash -c、powershell -Command、cmd /c、Invoke-Expression：回傳 (方言, 命令)。"""
    if verb in _POSIX_SHELLS:
        text = _shell_command(args)
        return ("bash", text) if text is not None else None
    if verb in _POWERSHELLS:
        text = _powershell_command(args)
        return ("powershell", text) if text is not None else None
    if verb == "cmd":
        for i, arg in enumerate(args):
            if arg.lower() in ("/c", "/k", "//c", "//k"):  # Git Bash 裡要寫成 //c
                return "cmd", " ".join(args[i + 1:])
        return None
    if verb in ("invoke-expression", "iex"):
        return "powershell", " ".join(a for a in args if not a.startswith("-"))
    return None


def _find_exec(args: list[str]) -> tuple[list[str], list[list[str]]]:
    """find：回傳 (起點, -exec／-execdir 執行的指令)。"""
    i = 0
    while i < len(args) and not args[i].startswith(("-", "!", "(")):
        i += 1
    starts, commands = args[:i] or ["."], []
    while i < len(args):
        if args[i].lower() in ("-exec", "-execdir", "-ok", "-okdir"):
            end = i + 1
            while end < len(args) and args[end] not in (";", "+"):
                end += 1
            commands.append(args[i + 1:end])
            i = end
        i += 1
    return starts, commands


def _non_options(args: list[str]) -> list[str]:
    """bash 指令的運算元：不是選項的字詞；-- 之後全部都是。"""
    out, options = [], True
    for arg in args:
        if options and arg == "--":
            options = False
        elif not (options and arg.startswith("-") and len(arg) > 1):
            out.append(arg)
    return out


def _bash_copy_move(args: list[str]) -> tuple[list[str], list[str]]:
    """GNU cp／mv：-t 或 --target-directory 指定目的地，否則最後一個運算元是目的地。"""
    dests: list[str] = []
    operands: list[str] = []
    i, options = 0, True
    while i < len(args):
        arg = args[i]
        if options and arg == "--":
            options = False
        elif options and arg.startswith("--"):
            name, eq, value = arg[2:].partition("=")
            if name and "target-directory".startswith(name):
                if not eq:
                    i += 1
                    value = args[i] if i < len(args) else ""
                dests.append(value)
            elif len(name) >= 2 and "suffix".startswith(name) and not eq:
                i += 1
        elif options and arg.startswith("-") and len(arg) > 1:
            letters = arg[1:]
            for j, letter in enumerate(letters):
                if letter in "tS":     # -t 目的地、-S 備份的字尾：值接在後面或是下一個字詞
                    value = letters[j + 1:]
                    if not value:
                        i += 1
                        value = args[i] if i < len(args) else ""
                    if letter == "t":
                        dests.append(value)
                    break
        else:
            operands.append(arg)
        i += 1
    if dests:
        return operands, dests
    return (operands[:-1], operands[-1:]) if len(operands) >= 2 else (operands, [])


def _ps_param(name: str, names: set[str]) -> str | None:
    """PowerShell 參數名稱：別名、全名，或不重複的前綴（-Dest、-Rec）。認不得時回傳 None。"""
    if name in _PS_ALIASES:
        return _PS_ALIASES[name]
    if name in names:
        return name
    found = {n for n in names if n.startswith(name)}
    found |= {full for alias, full in _PS_ALIASES.items() if alias.startswith(name) and full in names}
    return found.pop() if len(found) == 1 else None


def _ps_bind(family: str, args: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """PowerShell 的參數分成具名參數（正式名稱 → 值）與位置參數。"""
    valued, switches = _PS_PARAMS[family]
    valued = valued | _PS_COMMON_VALUED
    names = valued | switches | _PS_COMMON_SWITCHES
    named: dict[str, list[str]] = {}
    positional: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-") and len(arg) > 1 and not arg[1].isdigit():
            name, colon, value = arg[1:].partition(":")   # -Path:x 的寫法
            param = _ps_param(name.lower(), names)
            if param in valued:
                if not colon:
                    i += 1
                    value = args[i] if i < len(args) else ""
                named.setdefault(param, []).append(value)
        else:
            positional.append(arg)
        i += 1
    return named, positional


def _ps_split(family: str, args: list[str]) -> tuple[list[str], list[str]]:
    """PowerShell：依參數名稱與位置（Path 在前、Destination 在後）分出 (路徑, 目的地)。"""
    named, positional = _ps_bind(family, args)
    paths = [value for param in _PS_PATHS for value in named.get(param, [])]
    if family == "delete":
        return paths + positional, []
    if family in ("content", "tee"):
        return paths or positional[:1], []
    dests = named.get("destination", [])
    if not dests:
        if not paths:
            paths, positional = positional[:1], positional[1:]
        dests, positional = positional[:1] or ["."], positional[1:]  # 沒給目的地：目前的資料夾
    return paths + positional, dests


def _split_args(family: str, verb: str, args: list[str], dialect: str) -> tuple[list[str], list[str]]:
    """把參數分成 (來源或要寫的檔, 目的地)，依 shell 的寫法。"""
    if dialect == "bash" and verb in _BASH_NATIVE:
        if family in ("copy", "move"):
            return _bash_copy_move(args)
        return _non_options(args), []
    if dialect == "cmd" and verb in _CMD_NATIVE:
        words = [a for a in args if not a.startswith("/")]  # cmd 的開關是 /s、/q
        if family in ("copy", "move"):
            return (words[:-1], words[-1:]) if len(words) >= 2 else (words, ["."])
        return words, []
    return _ps_split(family, args)


def _is_placeholder(word: str, family: str) -> bool:
    """代表管線上游項目的字詞：$_、$PSItem、find 與 xargs 的 {}。刪除與搬移時，單獨的
    變數（$f、$item.FullName）也算；$env:TEMP\\x 這類組出來的路徑不算。"""
    w = _norm(word)
    if "{}" in w or w.startswith(("$_", "$psitem")):
        return True
    return family in ("delete", "move") and w.startswith(("$", "%")) and "/" not in w


def _targets(family: str, verb: str, args: list[str], dialect: str,
             pipeline: list[str], via_xargs: bool) -> list[str]:
    """寫入型動作會寫入、刪除或搬移的路徑（原始字詞）。"""
    sources, dests = _split_args(family, verb, args, dialect)
    if family == "copy":
        return dests                                   # 複製的來源只是讀取
    if family != "tee" and (via_xargs or all(_is_placeholder(w, family) for w in sources)):
        # 路徑來自管線：Get-ChildItem … | Remove-Item、ls … | xargs rm、{ Remove-Item $_ }
        sources = sources + pipeline
    return sources + dests


class _Checker:
    """逐段找出寫入型動作的目標；碰到受保護的路徑就回傳擋下的說明。"""

    def __init__(self, cwd: str):
        self.cwd = cwd                                 # payload 的 cwd（已正規化）

    def scan(self, text: str, dialect: str, here: str | None = None, depth: int = 0) -> str | None:
        if depth > 3:                                  # 巢狀的 bash -c、powershell -Command
            return None
        lexer = _Lexer(text, dialect)
        here = self.cwd if here is None else here      # 目前的資料夾，跟著 cd 走
        for statement in lexer.run():
            for k, seg in enumerate(statement):
                found, here = self._segment(seg, statement[:k], lexer, dialect, here, depth)
                if found:
                    return found
        return None

    def _segment(self, seg: _Seg, upstream: list[_Seg], lexer: _Lexer, dialect: str,
                 here: str, depth: int) -> tuple[str | None, str]:
        """回傳 (擋下的說明或 None, 之後的目前資料夾)。"""
        words = seg.words
        start, via_xargs = _command_start(words)
        verb = _command_name(words[start]) if start < len(words) else ""
        args = words[start + 1:]
        targets = list(seg.writes)

        if verb == "git" and _is_git_clean(args):
            return f"拒絕執行 {' '.join(words[start:])}：{GIT_CLEAN_REASON}。", here
        if verb in _CD:
            return None, self._cd(args, here)
        nested = _nested_command(verb, args)
        if nested:
            found = self.scan(nested[1], nested[0], here, depth + 1)
            if found:
                return found, here
        if verb == "find":
            starts, commands = _find_exec(args)
            for command in commands:
                found, _ = self._segment(_Seg(command), [_Seg(["find", *starts])], lexer, dialect, here, depth)
                if found:
                    return found, here
        family = _FAMILY.get(verb)
        if family:
            pipeline = [w for s in upstream for w in s.words if not w.startswith("-")]
            targets += _targets(family, verb, args, dialect, pipeline, via_xargs)
        return self._first_protected(targets, lexer, here), here

    def _cd(self, args: list[str], here: str) -> str:
        dirs = [a for a in args if not a.startswith("-")]
        if not dirs or "\x00" in dirs[-1] or dirs[-1].startswith(("$", "~", "%")):
            return self.cwd                            # 不知道切到哪裡：退回 payload 的 cwd
        return "/".join(_resolve(dirs[-1], here))

    def _first_protected(self, words: list[str], lexer: _Lexer, here: str) -> str | None:
        bases = [here] if here == self.cwd else [here, self.cwd]
        for word in words:
            for candidate in _candidates(word, lexer.groups):
                for base in bases:
                    reason = _path_reason(_resolve(candidate, base))
                    if reason:
                        return f"拒絕執行：這個命令會寫入、刪除或搬移 {candidate}。{reason}。"
        return None


def check(payload: dict) -> str | None:
    """找出這次工具呼叫裡受保護的寫入，回傳擋下的說明；沒有就回傳 None。"""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    cwd = _norm(str(payload.get("cwd") or ""))
    for key in ("file_path", "notebook_path"):
        path = tool_input.get(key)
        if isinstance(path, str) and path:
            reason = _path_reason(_resolve(path, cwd))
            if reason:
                return f"拒絕寫入 {path}：{reason}。"
    command = tool_input.get("command")
    if isinstance(command, str) and command.strip():
        # 不知道是哪個 shell 時，兩種寫法都檢查
        for dialect in _DIALECTS.get(payload.get("tool_name"), ("bash", "powershell")):
            found = _Checker(cwd).scan(command, dialect)
            if found:
                return found
    return None


def _read_payload() -> dict:
    # Claude Code 送的是 UTF-8。Windows 的 stdin 預設用系統碼頁（例如 GBK）解碼，
    # 中文會讓 JSON 解析失敗，所以直接讀位元組自己解碼。utf-8-sig 順便去掉
    # Windows PowerShell 5.1 用管線送資料時加在前面的 BOM
    stream = getattr(sys.stdin, "buffer", None)
    raw = stream.read().decode("utf-8-sig") if stream is not None else sys.stdin.read()
    payload = json.loads(raw.removeprefix("\ufeff"))
    if not isinstance(payload, dict):
        raise ValueError("最外層不是 JSON 物件")
    return payload


def main() -> int:
    try:
        payload = _read_payload()
    except Exception as e:
        print(
            f"受保護路徑的 hook 讀不到這次工具呼叫的 payload（{type(e).__name__}: {e}），先擋下。"
            "這是 hook 或 Claude Code 設定的問題，請使用者檢查；不要改用其他寫法繞過。",
            file=sys.stderr,
        )
        return 2
    try:
        found = check(payload)
    except Exception as e:  # hook 自己的錯：擋下並說明，不靜默放行
        print(
            f"受保護路徑的 hook 檢查時出錯（{type(e).__name__}: {e}），先擋下。"
            "請使用者修正 .claude/hooks/protect_paths.py；不要改用其他寫法繞過。",
            file=sys.stderr,
        )
        return 2
    if found is None:
        return 0
    print(f"{found}\n{POLICY}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
