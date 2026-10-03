"""
武器切换系统 - 核心模块（已修复）

修复内容：
- start_switch 正确驱动切换状态机，动画完成后才允许开火
- can_fire 检查切换状态与换弹状态，切换/换弹中禁止开火
- 切换时长按武器配置（单武器时长 + 武器对时长），不再写死 0.3s
- 切换时取消旧武器的换弹状态，切回后需要重新换弹
- 快速连切正确转换状态：放下阶段改向目标、举起阶段完成当前举起后链式切换，
  不再死锁，也不会重复播放完整动画导致切换时间翻倍
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------

class SwitchState:
    """切换状态机状态"""
    IDLE = "idle"                # 空闲，当前武器在手，可开火
    LOWERING = "lowering"        # 正在放下旧武器
    RAISING = "raising"          # 正在举起新武器


class AnimState:
    """单把武器的动画状态"""
    IDLE = "idle"
    LOWERING = "lowering"
    RAISING = "raising"
    RELOADING = "reloading"


DEFAULT_SWITCH_DURATION = 0.3   # 默认切换总时长（秒）
DEFAULT_RELOAD_DURATION = 2.0   # 默认换弹时长（秒）


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Config:
    """配置项"""
    default_switch_duration: float = DEFAULT_SWITCH_DURATION
    default_reload_duration: float = DEFAULT_RELOAD_DURATION
    # 单武器切换总时长：{weapon_name: seconds}
    weapon_switch_durations: Dict[str, float] = field(default_factory=dict)
    # 武器对切换总时长：{(from, to): seconds}，优先级最高
    pair_switch_durations: Dict[Tuple[str, str], float] = field(default_factory=dict)


@dataclass
class Weapon:
    """单把武器的运行时状态"""
    name: str
    switch_duration: float = DEFAULT_SWITCH_DURATION
    reload_duration: float = DEFAULT_RELOAD_DURATION
    equipped: bool = False
    anim_state: str = AnimState.IDLE
    is_reloading: bool = False
    reload_timer: float = 0.0


# ---------------------------------------------------------------------------
# 核心类
# ---------------------------------------------------------------------------

class WeaponSwitcher:
    """武器切换系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        cfg = config or {}
        self.config = Config(
            default_switch_duration=cfg.get("default_switch_duration", DEFAULT_SWITCH_DURATION),
            default_reload_duration=cfg.get("default_reload_duration", DEFAULT_RELOAD_DURATION),
            weapon_switch_durations=dict(cfg.get("weapon_switch_durations", {})),
            pair_switch_durations=dict(cfg.get("pair_switch_durations", {})),
        )
        self._weapons: Dict[str, Weapon] = {}
        self._order: List[str] = []
        self._current: Optional[str] = None

        # 切换状态机
        self._state: str = SwitchState.IDLE
        self._target: Optional[str] = None       # 本次切换的目标武器
        self._phase_timer: float = 0.0           # 当前阶段已进行时间
        self._phase_duration: float = 0.0        # 当前阶段总时长
        self._pending: Optional[str] = None      # 举起阶段排队的下一次切换目标

        self._history: List[Tuple[str, str]] = []

    # ------------------------------------------------------------------
    # 武器管理
    # ------------------------------------------------------------------

    def add_weapon(self, name: str,
                   switch_duration: Optional[float] = None,
                   reload_duration: Optional[float] = None,
                   equip: bool = False) -> Weapon:
        """注册一把武器。第一把武器默认装备在手。"""
        duration = switch_duration
        if duration is None:
            duration = self.config.weapon_switch_durations.get(
                name, self.config.default_switch_duration)
        weapon = Weapon(
            name=name,
            switch_duration=duration,
            reload_duration=self.config.default_reload_duration,
        )
        self._weapons[name] = weapon
        if name not in self._order:
            self._order.append(name)
        if self._current is None or equip:
            self._equip_initial(name)
        return weapon

    def _equip_initial(self, name: str):
        for weapon in self._weapons.values():
            weapon.equipped = False
        weapon = self._weapons[name]
        weapon.equipped = True
        weapon.anim_state = AnimState.IDLE
        self._current = name

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    @property
    def current_weapon(self) -> Optional[str]:
        return self._current

    @property
    def current_index(self) -> int:
        if self._current is None:
            return -1
        return self._order.index(self._current)

    @property
    def state(self) -> str:
        return self._state

    @property
    def target_weapon(self) -> Optional[str]:
        return self._target

    @property
    def is_switching(self) -> bool:
        return self._state != SwitchState.IDLE

    @property
    def switch_progress(self) -> float:
        """当前阶段进度 0.0 ~ 1.0"""
        if not self.is_switching or self._phase_duration <= 0:
            return 1.0
        return min(1.0, self._phase_timer / self._phase_duration)

    def get_anim_state(self, name: str) -> str:
        return self._weapons[name].anim_state

    def is_equipped(self, name: str) -> bool:
        return self._weapons[name].equipped

    def is_reloading(self, name: Optional[str] = None) -> bool:
        weapon = self._weapons[name or self._current]
        return weapon.is_reloading

    def reload_progress(self, name: Optional[str] = None) -> float:
        weapon = self._weapons[name or self._current]
        if not weapon.is_reloading or weapon.reload_duration <= 0:
            return 0.0
        return min(1.0, weapon.reload_timer / weapon.reload_duration)

    # ------------------------------------------------------------------
    # 切换时长配置
    # ------------------------------------------------------------------

    def switch_duration(self, from_weapon: str, to_weapon: str) -> float:
        """两把武器之间的切换总时长。

        优先级：武器对配置 > 目标武器单武器配置 > 全局默认。
        """
        pair = self.config.pair_switch_durations.get((from_weapon, to_weapon))
        if pair is not None:
            return pair
        return self._weapons[to_weapon].switch_duration

    # ------------------------------------------------------------------
    # 切换
    # ------------------------------------------------------------------

    def start_switch(self, target: str) -> bool:
        """请求切换到 target 武器。返回是否接受了该请求。"""
        if target not in self._weapons:
            return False

        if self._state == SwitchState.IDLE:
            if target == self._current:
                return False
            self._begin_switch(target)
            return True

        if self._state == SwitchState.LOWERING:
            # 放下阶段改向：直接更换目标，放下动画不重新播放
            if target == self._current:
                # 取消切换，回到当前武器
                self._cancel_switch()
                return True
            if target == self._target:
                return True
            # 改向：不重放放下动画，只按新目标重算该阶段总时长（已用时间保留）
            self._target = target
            self._phase_duration = self.switch_duration(self._current, target) / 2.0
            return True

        # RAISING：先把当前这把举完，再链式切换，避免动画从头播放
        if target == self._target:
            return True
        self._pending = target
        return True

    def double_switch(self, target: str) -> bool:
        """切换过程中再次切枪（快速连切）。语义与 start_switch 一致。"""
        return self.start_switch(target)

    def _begin_switch(self, target: str):
        """从 IDLE 开始一次切换：先放下当前武器。"""
        old = self._weapons[self._current]
        self._cancel_reload(old)
        old.anim_state = AnimState.LOWERING

        self._state = SwitchState.LOWERING
        self._target = target
        total = self.switch_duration(self._current, target)
        self._phase_duration = total / 2.0
        self._phase_timer = 0.0
        self._history.append((self._current, target))

    def _cancel_switch(self):
        """放下阶段切回当前武器：直接复原，不再播放动画。"""
        old = self._weapons[self._current]
        old.anim_state = AnimState.IDLE
        self._state = SwitchState.IDLE
        self._target = None
        self._pending = None
        self._phase_timer = 0.0
        self._phase_duration = 0.0

    def _finish_lowering(self):
        """放下完成：旧武器收起重置动画，新武器开始举起。"""
        old = self._weapons[self._current]
        old.equipped = False
        old.anim_state = AnimState.IDLE

        new = self._weapons[self._target]
        self._cancel_reload(new)
        new.equipped = True
        new.anim_state = AnimState.RAISING
        self._current = new.name

        self._state = SwitchState.RAISING
        self._phase_timer = 0.0
        # 举起阶段时长按（旧 -> 新）武器对计算
        total = self.switch_duration(old.name, new.name)
        self._phase_duration = total / 2.0

    def _finish_raising(self):
        """举起完成。若有排队目标则链式进入下一次放下。"""
        weapon = self._weapons[self._current]
        weapon.anim_state = AnimState.IDLE

        pending = self._pending
        self._pending = None
        if pending is not None and pending != self._current:
            self._begin_switch(pending)
        else:
            self._state = SwitchState.IDLE
            self._target = None
            self._phase_timer = 0.0
            self._phase_duration = 0.0

    # ------------------------------------------------------------------
    # 换弹
    # ------------------------------------------------------------------

    def start_reload(self) -> bool:
        """当前武器开始换弹。切换中不可换弹。"""
        if self._current is None or self.is_switching:
            return False
        weapon = self._weapons[self._current]
        if weapon.is_reloading:
            return False
        weapon.is_reloading = True
        weapon.reload_timer = 0.0
        weapon.anim_state = AnimState.RELOADING
        return True

    def _cancel_reload(self, weapon: Weapon):
        """取消换弹：清空进度并复位动画。"""
        if weapon.is_reloading:
            weapon.is_reloading = False
            weapon.reload_timer = 0.0
            if weapon.anim_state == AnimState.RELOADING:
                weapon.anim_state = AnimState.IDLE

    # ------------------------------------------------------------------
    # 开火
    # ------------------------------------------------------------------

    def can_fire(self) -> bool:
        """只有空闲状态、当前武器未在换弹时才允许开火。"""
        if self._state != SwitchState.IDLE or self._current is None:
            return False
        return not self._weapons[self._current].is_reloading

    def fire(self) -> bool:
        """尝试开火，返回是否成功。"""
        return self.can_fire()

    # ------------------------------------------------------------------
    # 帧更新
    # ------------------------------------------------------------------

    def update(self, dt: float):
        """每帧更新切换状态机与换弹进度。"""
        if dt <= 0:
            return

        if self._state == SwitchState.LOWERING:
            self._phase_timer += dt
            if self._phase_timer >= self._phase_duration:
                self._finish_lowering()
        elif self._state == SwitchState.RAISING:
            self._phase_timer += dt
            if self._phase_timer >= self._phase_duration:
                self._finish_raising()

        # 只有手持且空闲的武器才推进换弹
        if self._current is not None:
            weapon = self._weapons[self._current]
            if weapon.is_reloading:
                weapon.reload_timer += dt
                if weapon.reload_timer >= weapon.reload_duration:
                    weapon.is_reloading = False
                    weapon.reload_timer = 0.0
                    if weapon.anim_state == AnimState.RELOADING:
                        weapon.anim_state = AnimState.IDLE

    # ------------------------------------------------------------------
    # 重置
    # ------------------------------------------------------------------

    def reset(self):
        """重置状态：回到第一把武器，清空切换与换弹状态。"""
        self._state = SwitchState.IDLE
        self._target = None
        self._pending = None
        self._phase_timer = 0.0
        self._phase_duration = 0.0
        self._history = []
        for weapon in self._weapons.values():
            weapon.equipped = False
            weapon.anim_state = AnimState.IDLE
            weapon.is_reloading = False
            weapon.reload_timer = 0.0
        self._current = None
        if self._order:
            self._equip_initial(self._order[0])
