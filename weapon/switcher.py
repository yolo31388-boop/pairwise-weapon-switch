"""
武器切换系统 - 核心模块（带bug版本）

已知问题：
- start_switch只改索引不等动画完成
- can_fire不检查切换状态
- 切换时长写死不按武器配置
- 切换时不取消换弹状态
- 快速连切状态机死锁
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math
import time


@dataclass
class Config:
    """配置项"""
    pass


class WeaponSwitcher:
    """武器切换系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._state = {}
        self._history = []

    def update(self, dt: float):
        """每帧更新"""
        pass

    def reset(self):
        """重置状态"""
        self._state = {}
        self._history = []
