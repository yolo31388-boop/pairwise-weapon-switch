"""
武器切换系统 - 验收测试

运行方式：python -m pytest tests/test_weapon_switch.py -q
共 12 个测试用例，覆盖：
1-3  状态机与开火互斥
4-6  按武器配置的切换时长
7-8  切换时取消换弹
9-10 单武器渲染（不会两把枪同时在手）
11-12 快速连切 / double_switch 状态转换
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from weapon.switcher import WeaponSwitcher, SwitchState, AnimState


def make_system(pair_durations=None, weapon_durations=None):
    """手枪(0.3s) / 步枪(0.4s) / 狙击枪(0.6s)，初始手持手枪。"""
    config = {
        "default_switch_duration": 0.3,
        "weapon_switch_durations": weapon_durations or {},
        "pair_switch_durations": pair_durations or {},
    }
    system = WeaponSwitcher(config)
    system.add_weapon("pistol")
    system.add_weapon("rifle", switch_duration=0.4)
    system.add_weapon("sniper", switch_duration=0.6)
    return system


def advance(system, seconds, step=0.001):
    elapsed = 0.0
    while elapsed < seconds - 1e-9:
        system.update(min(step, seconds - elapsed))
        elapsed += step
    return elapsed


class TestWeaponSwitcher:
    """武器切换系统测试套件"""

    def setup_method(self):
        self.system = make_system()

    # ---- 1. 切换中不能开火，动画完成后才能开火（无额外延迟） ----
    def test_case_01(self):
        assert self.system.can_fire() is True
        assert self.system.start_switch("rifle") is True

        assert self.system.is_switching is True
        assert self.system.can_fire() is False

        advance(self.system, 0.19)  # 完成一半
        assert self.system.can_fire() is False

        advance(self.system, 0.02)  # 0.2s 放下完成，举起开始，仍不可开火
        assert self.system.state == SwitchState.RAISING
        assert self.system.can_fire() is False

        advance(self.system, 0.20)  # 0.4s 整个切换完成
        assert self.system.state == SwitchState.IDLE
        assert self.system.current_weapon == "rifle"
        assert self.system.can_fire() is True
        assert self.system.fire() is True

    # ---- 2. can_fire 检查状态机：切换刚完成的那一帧即可开火（无0.5s延迟） ----
    def test_case_02(self):
        self.system.start_switch("sniper")
        advance(self.system, 0.30)
        assert self.system.can_fire() is False
        # 狙击枪默认时长 0.6s
        advance(self.system, 0.30 + 1e-3)
        assert self.system.state == SwitchState.IDLE
        assert self.system.current_weapon == "sniper"
        assert self.system.can_fire() is True

    # ---- 3. 无武器时与不存在的目标 ----
    def test_case_03(self):
        empty = WeaponSwitcher()
        assert empty.can_fire() is False
        assert empty.start_switch("ghost") is False
        assert empty.is_switching is False

    # ---- 4. 切换时长按武器配置，不再写死 0.3s（狙击更慢） ----
    def test_case_04(self):
        assert abs(self.system.switch_duration("pistol", "sniper") - 0.6) < 1e-9
        assert abs(self.system.switch_duration("sniper", "pistol") - 0.3) < 1e-9

        self.system.start_switch("sniper")
        advance(self.system, 0.30)
        assert self.system.is_switching is True  # 0.3s 还没切完（旧bug写死时长会已完成）
        advance(self.system, 0.30 + 1e-3)
        assert self.system.state == SwitchState.IDLE

    # ---- 5. 武器对配置优先级最高，且方向敏感（狙->手快，手->狙慢） ----
    def test_case_05(self):
        system = make_system(pair_durations={
            ("sniper", "pistol"): 0.2,
            ("pistol", "sniper"): 0.8,
        })
        assert abs(system.switch_duration("sniper", "pistol") - 0.2) < 1e-9
        assert abs(system.switch_duration("pistol", "sniper") - 0.8) < 1e-9

        system.start_switch("sniper")
        advance(system, 0.8 + 1e-3)
        assert system.current_weapon == "sniper"

        system.start_switch("pistol")
        advance(system, 0.2 + 1e-3)
        assert system.state == SwitchState.IDLE
        assert system.current_weapon == "pistol"

    # ---- 6. 武器对配置也可通过配置字典中的单武器时长生效 ----
    def test_case_06(self):
        system = make_system(weapon_durations={"shotgun": 0.5})
        system.add_weapon("shotgun")
        assert abs(system.switch_duration("pistol", "shotgun") - 0.5) < 1e-9
        system.start_switch("shotgun")
        advance(system, 0.5 + 1e-3)
        assert system.state == SwitchState.IDLE
        assert system.current_weapon == "shotgun"

    # ---- 7. 放下时取消旧武器换弹：切回后换弹进度与状态都清空 ----
    def test_case_07(self):
        self.system.start_reload()
        assert self.system.is_reloading("pistol") is True
        assert self.system.get_anim_state("pistol") == AnimState.RELOADING

        self.system.start_switch("rifle")
        # 一开始换弹就被取消
        assert self.system.is_reloading("pistol") is False
        assert self.system.get_anim_state("pistol") == AnimState.LOWERING
        assert self.system.reload_progress("pistol") == 0.0

        advance(self.system, 0.4 + 1e-3)
        assert self.system.state == SwitchState.IDLE
        self.system.start_switch("pistol")
        advance(self.system, 0.3 + 1e-3)
        # 切回来时没有残留换弹：可以立即开火
        assert self.system.is_reloading("pistol") is False
        assert self.system.get_anim_state("pistol") == AnimState.IDLE
        assert self.system.can_fire() is True

    # ---- 8. 换弹中不能开火；换弹完成后恢复 ----
    def test_case_08(self):
        assert self.system.start_reload() is True
        assert self.system.can_fire() is False
        advance(self.system, 2.0 + 1e-3)
        assert self.system.is_reloading() is False
        assert self.system.can_fire() is True

    # ---- 9. 切换的任意时刻只有一把武器 equipped（不会两把枪同时在手） ----
    def test_case_09(self):
        self.system.start_switch("sniper")
        # 放下阶段：只有旧武器 equipped
        self.system.start_switch("sniper")
        advance(self.system, 0.2)
        equipped = [n for n in ("pistol", "rifle", "sniper") if self.system.is_equipped(n)]
        assert equipped == ["pistol"]
        assert self.system.get_anim_state("pistol") == AnimState.LOWERING
        assert self.system.get_anim_state("sniper") == AnimState.IDLE

        # 阶段交接：旧武器收起重置，新武器举起
        advance(self.system, 0.10 + 1e-3)
        equipped = [n for n in ("pistol", "rifle", "sniper") if self.system.is_equipped(n)]
        assert equipped == ["sniper"]
        assert self.system.get_anim_state("pistol") == AnimState.IDLE
        assert self.system.get_anim_state("sniper") == AnimState.RAISING

        # 完成
        advance(self.system, 0.30 + 1e-3)
        assert self.system.get_anim_state("sniper") == AnimState.IDLE
        assert self.system.can_fire() is True

    # ---- 10. 快速连按切枪键不会死锁：反复请求最终一定回到 IDLE ----
    def test_case_10(self):
        self.system.start_switch("sniper")
        advance(self.system, 0.1)
        self.system.start_switch("rifle")   # 放下阶段改向（阶段总时长重算为0.2）
        advance(self.system, 0.05)
        self.system.start_switch("pistol")  # 又改回原武器：取消切换
        assert self.system.state == SwitchState.IDLE
        assert self.system.current_weapon == "pistol"
        assert self.system.can_fire() is True

        # 大量随机连按也不会卡状态机
        self.system.start_switch("sniper")
        for _ in range(50):
            advance(self.system, 0.05)
            self.system.start_switch("rifle")
            self.system.start_switch("sniper")
        advance(self.system, 5.0)
        assert self.system.state == SwitchState.IDLE
        assert self.system.is_switching is False

    # ---- 11. double_switch：举起阶段连切 -> 链式切换，动画不从头播放 ----
    def test_case_11(self):
        # pistol(0.3) -> sniper(0.6)：放下0.15 + 举起0.3 = 0.45 时改切 rifle
        self.system.start_switch("sniper")
        advance(self.system, 0.45)
        assert self.system.state == SwitchState.RAISING
        assert self.system.double_switch("rifle") is True
        # 当前举起动画继续，不会从头开始：再走 0.15 就举起完成
        advance(self.system, 0.15 + 1e-3)
        assert self.system.current_weapon == "sniper"
        assert self.system.state == SwitchState.LOWERING  # 链式放下

        # sniper -> rifle 总时长按目标 rifle 的 0.4s
        advance(self.system, 0.20 + 1e-3)  # 放下 0.2
        assert self.system.state == SwitchState.RAISING
        advance(self.system, 0.20 + 1e-3)  # 举起 0.2
        assert self.system.state == SwitchState.IDLE
        assert self.system.current_weapon == "rifle"
        assert self.system.can_fire() is True

        # 总耗时 1.0s；旧bug从头播放会多花 0.6s（约 1.6s）
        assert self.system.is_switching is False

    # ---- 12. 放下阶段 double_switch 直接改向，不重启动画，总时长不翻倍 ----
    def test_case_12(self):
        # pistol -> sniper：放下阶段持续 0.3s（狙总时长0.6的一半）
        self.system.start_switch("sniper")
        advance(self.system, 0.15)
        # 改向 rifle（总时长0.4，放下一半0.2）：已过去0.15，再走0.05完成放下
        assert self.system.double_switch("rifle") is True
        assert self.system.target_weapon == "rifle"
        advance(self.system, 0.05 + 1e-3)
        assert self.system.state == SwitchState.RAISING
        assert self.system.current_weapon == "rifle"
        advance(self.system, 0.20 + 1e-3)
        assert self.system.state == SwitchState.IDLE
        assert self.system.current_weapon == "rifle"
        # 旧bug从头播放放下动画需要 0.2 而非 0.05，总时长约 0.6；现在只需 0.4
        assert self.system.can_fire() is True


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
