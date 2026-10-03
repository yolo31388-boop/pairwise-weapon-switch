"""
武器切换系统 - 核心模块（修复版）

修复内容：
- start_switch 驱动完整切换状态机，动画完成后才落到目标武器
- can_fire 检查切换状态机与换弹状态，切换/换弹期间禁止开火
- 切换时长按武器对配置（收起时长 + 举起时长），不再写死 0.3s
- 切换时取消上一把武器的换弹状态并清空换弹进度
- 切换中再次切枪（double_switch）重定向目标并保留动画进度，状态机不死锁
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Config:
    """配置项"""
    pass


class WeaponSwitcher:
    """武器切换系统核心类"""

    STATE_IDLE = "idle"
    STATE_SWITCHING = "switching"

    ANIM_IDLE = "idle"
    ANIM_SWITCHING = "switching"

    # 每把武器默认的收起/举起/换弹时长（秒）
    DEFAULT_WEAPONS: Dict[str, Dict[str, float]] = {
        "pistol": {"switch_out": 0.10, "switch_in": 0.20, "reload_time": 1.2},
        "rifle": {"switch_out": 0.10, "switch_in": 0.30, "reload_time": 2.0},
        "sniper": {"switch_out": 0.10, "switch_in": 0.50, "reload_time": 3.0},
    }

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._weapons: Dict[str, Dict[str, float]] = {}
        configured = self.config.get("weapons", {})
        for name, defaults in self.DEFAULT_WEAPONS.items():
            merged = dict(defaults)
            merged.update(configured.get(name, {}))
            self._weapons[name] = merged
        for name, weapon_cfg in configured.items():
            if name not in self._weapons:
                self._weapons[name] = dict(weapon_cfg)
        # 可选的逐武器对切换时长覆盖：{"switch_times": {"sniper": {"pistol": 0.2}}}
        self._switch_times: Dict[str, Dict[str, float]] = self.config.get("switch_times", {})
        self._initial_weapon = self.config.get("initial_weapon", "pistol")
        self._state: Dict = {}
        self._history: List[Tuple] = []
        self.reset()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state["state"]

    @property
    def current_weapon(self) -> str:
        return self._state["current_weapon"]

    @property
    def target_weapon(self) -> Optional[str]:
        return self._state["target_weapon"]

    def is_switching(self) -> bool:
        return self._state["state"] == self.STATE_SWITCHING

    def can_fire(self) -> bool:
        """只有状态机空闲且当前武器不在换弹时才允许开火"""
        if self.is_switching():
            return False
        return not self.is_reloading(self.current_weapon)

    def is_reloading(self, weapon: Optional[str] = None) -> bool:
        weapon = weapon or self.current_weapon
        return self._weapon_runtime(weapon)["reloading"]

    def reload_progress(self, weapon: Optional[str] = None) -> float:
        weapon = weapon or self.current_weapon
        runtime = self._weapon_runtime(weapon)
        if not runtime["reloading"]:
            return 0.0
        reload_time = self._weapons[weapon].get("reload_time", 0.0)
        if reload_time <= 0:
            return 1.0
        return min(runtime["reload_elapsed"] / reload_time, 1.0)

    def animation_state(self, weapon: str) -> str:
        return self._weapon_runtime(weapon)["anim"]

    def visible_weapons(self) -> List[str]:
        """任意时刻只渲染一把武器，避免两把枪同时举在手上"""
        return [self.current_weapon]

    def switch_animation(self) -> Optional[Dict]:
        """当前切换动画信息；不在切换中返回 None"""
        if not self.is_switching():
            return None
        elapsed = self._state["switch_elapsed"]
        duration = self._state["switch_duration"]
        return {
            "from": self._state["switch_from"],
            "to": self._state["target_weapon"],
            "elapsed": elapsed,
            "duration": duration,
            "progress": min(elapsed / duration, 1.0) if duration > 0 else 1.0,
        }

    @property
    def history(self) -> List[Tuple]:
        return list(self._history)

    # ------------------------------------------------------------------
    # 切换时长
    # ------------------------------------------------------------------
    def switch_duration(self, from_weapon: str, to_weapon: str) -> float:
        """切换时长 = 收起当前武器 + 举起目标武器，可按武器对覆盖"""
        pair = self._switch_times.get(from_weapon, {})
        if to_weapon in pair:
            return pair[to_weapon]
        return (
            self._weapons[from_weapon].get("switch_out", 0.0)
            + self._weapons[to_weapon].get("switch_in", 0.0)
        )

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------
    def start_switch(self, target: str) -> bool:
        """发起切换。切换中再次调用会重定向目标并保留动画进度"""
        if target not in self._weapons:
            return False
        if self.is_switching():
            return self._retarget(target)
        if target == self.current_weapon:
            return False
        source = self.current_weapon
        self._cancel_reload(source)
        self._weapon_runtime(source)["anim"] = self.ANIM_IDLE
        self._state["state"] = self.STATE_SWITCHING
        self._state["switch_from"] = source
        self._state["target_weapon"] = target
        self._state["switch_elapsed"] = 0.0
        self._state["switch_duration"] = self.switch_duration(source, target)
        self._weapon_runtime(source)["anim"] = self.ANIM_SWITCHING
        self._history.append(("switch_start", source, target))
        return True

    def double_switch(self, target: str) -> bool:
        """切换过程中再次切枪：重定向目标，动画不清零重播"""
        return self.start_switch(target)

    def start_reload(self) -> bool:
        """当前武器开始换弹；切换中不允许换弹"""
        if self.is_switching():
            return False
        runtime = self._weapon_runtime(self.current_weapon)
        if runtime["reloading"]:
            return False
        runtime["reloading"] = True
        runtime["reload_elapsed"] = 0.0
        self._history.append(("reload_start", self.current_weapon))
        return True

    def update(self, dt: float):
        """每帧更新：推进切换动画与换弹计时"""
        if dt < 0:
            return
        if self.is_switching():
            self._state["switch_elapsed"] += dt
            if self._state["switch_elapsed"] >= self._state["switch_duration"]:
                self._complete_switch()
        runtime = self._weapon_runtime(self.current_weapon)
        if runtime["reloading"]:
            runtime["reload_elapsed"] += dt
            reload_time = self._weapons[self.current_weapon].get("reload_time", 0.0)
            if runtime["reload_elapsed"] >= reload_time:
                runtime["reloading"] = False
                runtime["reload_elapsed"] = 0.0
                self._history.append(("reload_complete", self.current_weapon))

    def reset(self):
        """重置状态"""
        self._state = {
            "state": self.STATE_IDLE,
            "current_weapon": self._initial_weapon,
            "target_weapon": None,
            "switch_from": None,
            "switch_elapsed": 0.0,
            "switch_duration": 0.0,
        }
        self._history = []
        self._runtime = {
            name: {"reloading": False, "reload_elapsed": 0.0, "anim": self.ANIM_IDLE}
            for name in self._weapons
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _weapon_runtime(self, weapon: str) -> Dict:
        return self._runtime[weapon]

    def _retarget(self, target: str) -> bool:
        """切换中改变目标：保留已播放的动画进度，避免总时长翻倍"""
        if target == self._state["target_weapon"]:
            return False
        source = self._state["switch_from"]
        if target == source:
            # 切回正在收起的武器：直接取消本次切换
            self._cancel_switch()
            return True
        self._state["target_weapon"] = target
        self._state["switch_duration"] = self.switch_duration(source, target)
        self._history.append(("switch_retarget", source, target))
        if self._state["switch_elapsed"] >= self._state["switch_duration"]:
            self._complete_switch()
        return True

    def _complete_switch(self):
        source = self._state["switch_from"]
        target = self._state["target_weapon"]
        self._weapon_runtime(source)["anim"] = self.ANIM_IDLE
        self._state["state"] = self.STATE_IDLE
        self._state["current_weapon"] = target
        self._state["target_weapon"] = None
        self._state["switch_from"] = None
        self._state["switch_elapsed"] = 0.0
        self._state["switch_duration"] = 0.0
        self._history.append(("switch_complete", source, target))

    def _cancel_switch(self):
        source = self._state["switch_from"]
        self._weapon_runtime(source)["anim"] = self.ANIM_IDLE
        self._state["state"] = self.STATE_IDLE
        self._state["target_weapon"] = None
        self._state["switch_from"] = None
        self._state["switch_elapsed"] = 0.0
        self._state["switch_duration"] = 0.0
        self._history.append(("switch_cancel", source))

    def _cancel_reload(self, weapon: str):
        runtime = self._weapon_runtime(weapon)
        if runtime["reloading"]:
            runtime["reloading"] = False
            runtime["reload_elapsed"] = 0.0
            self._history.append(("reload_cancel", weapon))
