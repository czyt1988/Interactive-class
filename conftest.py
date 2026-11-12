"""pytest 入口：保证测试导入的是当前检出目录里的 ``app`` 与 ``scripts``。

多个 git 工作树共用主工作树的 ``.venv``（见 ``scripts/worktree.py``），而共享
虚拟环境里的 editable install 指向主工作树。用 ``pytest.exe`` 这类控制台脚本
启动时，``sys.path`` 里没有当前工作树的根目录，``import app`` 会拿到主工作树的
代码——测试就会在错的源码上运行。这里统一把仓库根放到 ``sys.path`` 最前面：

- 在哪个检出目录里跑 pytest，就导入哪个检出的代码；
- 顺带让 ``tests/`` 里 ``from scripts.build_courses import ...`` 这种导入在
  两种启动方式下都成立。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
