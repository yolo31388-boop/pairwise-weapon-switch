# 武器切换系统

## 项目描述

武器切换系统的bug修复项目。核心模块 `weapon/switcher.py` 存在多个已知bug，需要修复后使测试全部通过。

## 已知问题

- start_switch只改索引不等动画完成
- can_fire不检查切换状态
- 切换时长写死不按武器配置
- 切换时不取消换弹状态
- 快速连切状态机死锁

## 项目结构

```
├── weapon/switcher.py       # 核心模块（带bug）
├── tests/test_weapon_switch.py    # 验收测试（红态）
├── pyproject.toml          # 项目配置
└── README.md               # 说明文档
```

## 运行测试

```bash
python -m pytest tests/test_weapon_switch.py -q
```

修复目标：所有 12 个测试全部通过。

## 技术要求

- 纯Python标准库，不引入第三方依赖
- 不修改测试文件
- 保持现有API接口不变
- 修复所有已知bug
