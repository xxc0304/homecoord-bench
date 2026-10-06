# C2-ROOM：设计证据卡

状态：待审。仅任务定义，不含运行成绩。完整状态、工具签名、动作效果与约束见 contracts.json 中本组。
任务模板、grounding 和 service 字段为审查者可见的执行/评分合同，不能据此认为全部进入决策者输入。
权限表的 observable_state 才是局部状态视图；公共信息与未来事件另按发布规则限制。

## 请求语义与验收边界

命令只改窗口/供暖执行器；环境按统一时钟演化。联合目标=温度>=21、CO2<=900且关窗，期限360000ms，共同终点900000ms。

未校准合成模型；只有首次观察达标，没有持续保持时长合同。冷热/CO2方程及积分定义见本包README，不验收真实舒适或持续舒适。

审查者需判断以上合同能否接受或应修改；它们是当前声明，不是已获批准的事实。

## 输入与配对参数

| 输入 ID | 任务 | 发布 ms | 截止 ms | 合格操作：持续 ms / 资源 |
|---|---|---:|---:|---|
| ROOM-1600-V2.5-H0.015-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V2.5-H0.015-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V2.5-H0.015-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V2.5-H0.015-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V2.5-H0.025-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V2.5-H0.025-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V2.5-H0.025-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V2.5-H0.025-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V2.5-H0.035-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V2.5-H0.035-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V2.5-H0.035-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V2.5-H0.035-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V5.0-H0.015-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V5.0-H0.015-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V5.0-H0.015-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V5.0-H0.015-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V5.0-H0.025-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V5.0-H0.025-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V5.0-H0.025-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V5.0-H0.025-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V5.0-H0.035-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V5.0-H0.035-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-1600-V5.0-H0.035-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-1600-V5.0-H0.035-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V2.5-H0.015-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V2.5-H0.015-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V2.5-H0.015-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V2.5-H0.015-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V2.5-H0.025-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V2.5-H0.025-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V2.5-H0.025-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V2.5-H0.025-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V2.5-H0.035-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V2.5-H0.035-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V2.5-H0.035-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V2.5-H0.035-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V5.0-H0.015-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V5.0-H0.015-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V5.0-H0.015-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V5.0-H0.015-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V5.0-H0.025-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V5.0-H0.025-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V5.0-H0.025-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V5.0-H0.025-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V5.0-H0.035-immediate | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V5.0-H0.035-immediate | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |
| ROOM-850-V5.0-H0.035-after_ventilation | bedroom_air | 0 | 未声明 | open: 2000 / 0 |
| ROOM-850-V5.0-H0.035-after_ventilation | bedroom_heat | 100 | 未声明 | heat_high: 1000 / 0 |

资源：C3-F* 的旧 power_kw 字段是抽象预约单位，不是实测 kW；其他组按作者定义参数解释，均未设备校准。
完整合法操作以工具签名、前提和服务匹配为准；off 即使合法也不提供请求服务。

## 权限与可见信息

| 输入 | 主体 | 可见状态 | 可写资源 | 工具 |
|---|---|---|---|---|
| ROOM-1600-V2.5-H0.015-immediate | AirQualityAgent | bedroom.temperature_c, bedroom.co2_ppm, devices.window, devices.heater | devices.window | set_window |
| ROOM-1600-V2.5-H0.015-immediate | HeatingAgent | bedroom.temperature_c, bedroom.co2_ppm, devices.window, devices.heater | devices.heater | set_heater |

上表对字段相同的主体去重；逐输入权限仍以 contracts.json 为准。服务回执由可信执行器写入，不授权主体直接写评分字段。

## 初态、容量与外源事件

### ROOM-1600-V2.5-H0.015-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.015,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V2.5-H0.015-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.015,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V2.5-H0.025-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.025,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V2.5-H0.025-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.025,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V2.5-H0.035-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.035,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V2.5-H0.035-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.035,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V5.0-H0.015-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.015,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V5.0-H0.015-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.015,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V5.0-H0.025-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.025,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V5.0-H0.025-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.025,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V5.0-H0.035-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.035,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-1600-V5.0-H0.035-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 1600
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.035,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V2.5-H0.015-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.015,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V2.5-H0.015-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.015,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V2.5-H0.025-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.025,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V2.5-H0.025-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.025,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V2.5-H0.035-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.035,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V2.5-H0.035-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 2.5,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.035,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V5.0-H0.015-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.015,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V5.0-H0.015-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.015,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V5.0-H0.025-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.025,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V5.0-H0.025-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.025,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V5.0-H0.035-immediate

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.035,
      "heater_power_kw": 2,
      "heat_admission": "immediate"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```

### ROOM-850-V5.0-H0.035-after_ventilation

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 106,
    "values": {
      "bedroom": {
        "temperature_c": 17,
        "co2_ppm": 850
      },
      "devices": {
        "window": "closed",
        "heater": "off"
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "environment": {
      "kind": "uncalibrated_room_v1",
      "calibration_status": "uncalibrated_synthetic",
      "source_note": "author assumptions, NOT causal calibration or realistic range",
      "parameter_reference": "docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md; observation audit rejects upgrading these rates",
      "tick_ms": 1000,
      "deadline_ms": 360000,
      "horizon_ms": 900000,
      "close_delay_ms": 3000,
      "outdoor_temp_c": 8,
      "target_temp_c": 21,
      "target_co2_ppm": 900,
      "co2_floor_ppm": 420,
      "ventilation_rate_ppm_s": 5.0,
      "exchange_per_s": 0.0015,
      "heat_rate_c_per_s": 0.035,
      "heater_power_kw": 2,
      "heat_admission": "after_ventilation"
    }
  },
  "constraints": [],
  "goals": [
    {
      "path": "bedroom.co2_ppm",
      "op": "lte",
      "value": 900
    },
    {
      "path": "bedroom.temperature_c",
      "op": "gte",
      "value": 21
    },
    {
      "path": "devices.window",
      "op": "eq",
      "value": "closed"
    }
  ]
}
```
