"""每个在运行时被读取的包内资源, 都必须真的进得了 wheel。

为什么需要这条: 2026-09-08 新增 `import_graph_policy.yaml` 时漏了
`pyproject.toml` 的 package-data。源码树里一切正常(文件就在旁边), 全套测试也全绿
—— 因为测试跑的是源码树。只有 `pip install` 之后才炸:
`files("moth").joinpath("import_graph_policy.yaml")` 抛 FileNotFoundError,
架构漂移核验整个不可用。

这类缺陷的特征是**在开发环境里不可见**, 所以它不会被任何跑源码树的测试发现,
只会被装了包的使用者发现。判据锚在两个一手源的比对上:
源码里 `files("moth")` 实际请求的资源名 vs pyproject 声明的 package-data 模式。

守谁: 装了 moth 的使用者。
守什么: 一句可判 —— 代码运行时会读的每个包内资源, 都在 package-data 的覆盖里。
对象消失时怎么死: 不再有任何 `files("moth")` 调用时, 扫描结果为空, 断言空集通过,
这条测试自然失效, 不留残骸。
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_ROOT = _REPO_ROOT / "src" / "moth"

# 跨行匹配: change_safety.py 里 files("moth") 与 .joinpath(...) 分处不同行。
_RESOURCE_CALL = re.compile(
    r"""files\(\s*["']moth["']\s*\)\s*(?:\r?\n\s*)?\.joinpath\(\s*(?:\r?\n\s*)?["']([^"']+)["']""",
    re.VERBOSE,
)


def _requested_resources() -> set[str]:
    found: set[str] = set()
    for path in _PACKAGE_ROOT.rglob("*.py"):
        found.update(_RESOURCE_CALL.findall(path.read_text(encoding="utf-8")))
    return found


def _declared_patterns() -> list[str]:
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(
        r"\[tool\.setuptools\.package-data\]\s*\nmoth\s*=\s*\[(.*?)\]",
        text,
        re.S,
    )
    assert block is not None, "pyproject.toml 里找不到 [tool.setuptools.package-data] 的 moth 条目"
    return re.findall(r'"([^"]+)"', block.group(1))


def test_every_runtime_resource_is_declared_as_package_data() -> None:
    patterns = _declared_patterns()
    requested = _requested_resources()

    # 空扫描等于没测 —— 若正则失配或调用全被重构掉, 必须红而不是静默通过。
    assert requested, "没有扫到任何 files(\"moth\") 资源请求, 检查正则是否失配"

    undeclared = sorted(
        name
        for name in requested
        if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
    )
    assert undeclared == [], (
        f"这些资源在运行时会被读取, 却不在 pyproject 的 package-data 里: {undeclared}。"
        " 源码树里察觉不到, 但 pip install 之后会 FileNotFoundError。"
    )


def test_declared_resources_actually_exist_in_the_package() -> None:
    """反向: 声明了却不存在的模式是过期条目, 会让人以为某个资源受保护。"""

    stale = [
        pattern
        for pattern in _declared_patterns()
        if not list(_PACKAGE_ROOT.glob(pattern))
    ]
    assert stale == [], f"package-data 声明了但包里不存在: {stale}"


@pytest.mark.parametrize(
    "resource",
    sorted(_requested_resources()),
)
def test_requested_resource_is_present_on_disk(resource: str) -> None:
    """请求的资源必须真的在源码树里 —— 否则连开发环境都是坏的。"""

    assert (_PACKAGE_ROOT / resource).is_file(), f"{resource} 不在 {_PACKAGE_ROOT}"
