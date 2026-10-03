"""
武器切换系统 - 验收测试

运行方式：python -m pytest tests/test_weapon_switch.py -q
共 12 个测试用例
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from weapon.switcher import WeaponSwitcher


class TestWeaponSwitcher:
    """武器切换系统测试套件"""

    def setup_method(self):
        """每个测试前的初始化"""
        self.system = WeaponSwitcher()

    def _finish_switch(self, timeout=10.0):
        """推进时间直到切换完成，防止死锁时无限循环"""
        elapsed = 0.0
        while self.system.is_switching():
            self.system.update(0.05)
            elapsed += 0.05
            assert elapsed < timeout, "切换状态机死锁，永远卡在切换中"

    def test_case_01(self):
        """初始状态：空闲、手持默认武器、可以开火"""
        assert self.system.state == WeaponSwitcher.STATE_IDLE
        assert self.system.current_weapon == "pistol"
        assert not self.system.is_switching()
        assert self.system.can_fire()
        assert self.system.switch_animation() is None

    def test_case_02(self):
        """start_switch 启动切换状态机，切换期间禁止开火"""
        assert self.system.start_switch("sniper") is True
        assert self.system.is_switching()
        assert self.system.target_weapon == "sniper"
        assert self.system.can_fire() is False
        anim = self.system.switch_animation()
        assert anim is not None
        assert anim["from"] == "pistol"
        assert anim["to"] == "sniper"

    def test_case_03(self):
        """切换动画播完后才落到目标武器并恢复开火"""
        self.system.start_switch("sniper")
        duration = self.system.switch_duration("pistol", "sniper")
        self.system.update(duration - 0.01)
        assert self.system.is_switching()
        assert self.system.current_weapon == "pistol"
        self.system.update(0.01)
        assert not self.system.is_switching()
        assert self.system.current_weapon == "sniper"
        assert self.system.can_fire()

    def test_case_04(self):
        """切换时长按武器配置：狙击切手枪比手枪切狙击快，且可配置"""
        fast = self.system.switch_duration("sniper", "pistol")
        slow = self.system.switch_duration("pistol", "sniper")
        assert fast < slow
        custom = WeaponSwitcher({"switch_times": {"sniper": {"pistol": 0.05}}})
        assert custom.switch_duration("sniper", "pistol") == pytest.approx(0.05)

    def test_case_05(self):
        """切换时旧武器动画状态被重置，任意时刻只渲染一把武器"""
        self.system.start_switch("sniper")
        assert self.system.animation_state("rifle") == "idle"
        assert len(self.system.visible_weapons()) == 1
        self._finish_switch()
        assert self.system.animation_state("pistol") == "idle"
        assert self.system.visible_weapons() == ["sniper"]

    def test_case_06(self):
        """can_fire 检查状态机：切换中与换弹中都禁止开火"""
        self.system.start_switch("rifle")
        assert not self.system.is_reloading()
        assert self.system.can_fire() is False
        self._finish_switch()
        assert self.system.can_fire()
        self.system.start_reload()
        assert self.system.can_fire() is False

    def test_case_07(self):
        """快速连按切枪键不会死锁，状态机最终回到空闲"""
        targets = ["sniper", "rifle", "pistol"]
        for i in range(30):
            self.system.start_switch(targets[i % 3])
            self.system.update(0.05)
        self._finish_switch()
        assert not self.system.is_switching()
        assert self.system.can_fire()

    def test_case_08(self):
        """切换时取消上一把武器的换弹状态并清空进度"""
        self.system.start_reload()
        self.system.update(0.5)
        assert self.system.reload_progress("pistol") > 0
        self.system.start_switch("rifle")
        assert not self.system.is_reloading("pistol")
        assert self.system.reload_progress("pistol") == 0.0

    def test_case_09(self):
        """换弹中切走再切回：换弹状态已取消，可重新换弹"""
        self.system.start_reload()
        self.system.update(0.3)
        self.system.start_switch("rifle")
        self._finish_switch()
        self.system.start_switch("pistol")
        self._finish_switch()
        assert self.system.current_weapon == "pistol"
        assert not self.system.is_reloading()
        assert self.system.reload_progress() == 0.0
        assert self.system.start_reload() is True

    def test_case_10(self):
        """double_switch 保留动画进度，总切换时长不翻倍"""
        self.system.start_switch("sniper")  # 0.6s
        self.system.update(0.2)
        assert self.system.double_switch("rifle") is True
        anim = self.system.switch_animation()
        assert anim["to"] == "rifle"
        assert anim["elapsed"] == pytest.approx(0.2)  # 进度保留，不从头播放
        assert anim["duration"] == pytest.approx(
            self.system.switch_duration("pistol", "rifle")
        )
        self.system.update(0.19)
        assert self.system.is_switching()
        self.system.update(0.01)  # 总计 0.4s 完成，而非 0.2 + 0.4
        assert self.system.current_weapon == "rifle"

    def test_case_11(self):
        """切换到当前武器或非法武器是无害空操作，状态机不卡死"""
        assert self.system.start_switch("pistol") is False
        assert self.system.start_switch("not_a_weapon") is False
        assert not self.system.is_switching()
        assert self.system.can_fire()

    def test_case_12(self):
        """reset 恢复初始状态，清除切换/换弹/历史记录"""
        self.system.start_reload()
        self.system.start_switch("sniper")
        self.system.update(0.1)
        self.system.reset()
        assert self.system.state == WeaponSwitcher.STATE_IDLE
        assert self.system.current_weapon == "pistol"
        assert self.system.can_fire()
        assert self.system.history == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
