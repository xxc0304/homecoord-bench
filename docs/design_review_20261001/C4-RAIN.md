# C4-RAIN：设计证据卡

状态：待审。仅任务定义，不含运行成绩。完整状态、工具签名、动作效果与约束见 contracts.json 中本组。
任务模板、grounding 和 service 字段为审查者可见的执行/评分合同，不能据此认为全部进入决策者输入。
权限表的 observable_state 才是局部状态视图；公共信息与未来事件另按发布规则限制。

## 请求语义与验收边界

降雨变真永久撤回本次灌溉请求；运行中须停止确认，雨停不复活；完成后事件不追溯撤回。

雨量阈值、用户偏好和实际供水量未建模；这里只用布尔事件和违规持续时间，不称雨已满足灌溉需求。

审查者需判断以上合同能否接受或应修改；它们是当前声明，不是已获批准的事实。

## 输入与配对参数

| 输入 ID | 任务 | 发布 ms | 截止 ms | 合格操作：持续 ms / 资源 |
|---|---|---:|---:|---|
| REV-C4-RAIN-NOEVENT-LC2 | water_garden | 0 | 10000 | water: 3000 / 0.1 |
| REV-C4-RAIN-NOEVENT-LC2 | observe_rain | 0 | 2000 | observe: 100 / 0.0 |
| REV-C4-RAIN-PRESTART-LC2 | water_garden | 0 | 10000 | water: 3000 / 0.1 |
| REV-C4-RAIN-PRESTART-LC2 | observe_rain | 0 | 2000 | observe: 100 / 0.0 |
| REV-C4-RAIN-INFLIGHT-LC2 | water_garden | 0 | 10000 | water: 3000 / 0.1 |
| REV-C4-RAIN-INFLIGHT-LC2 | observe_rain | 0 | 2000 | observe: 100 / 0.0 |
| REV-C4-RAIN-POSTCOMPLETE-LC2 | water_garden | 0 | 10000 | water: 3000 / 0.1 |
| REV-C4-RAIN-POSTCOMPLETE-LC2 | observe_rain | 0 | 2000 | observe: 100 / 0.0 |
| REV-C4-RAIN-UNRELATED-LC2 | water_garden | 0 | 10000 | water: 3000 / 0.1 |
| REV-C4-RAIN-UNRELATED-LC2 | observe_rain | 0 | 2000 | observe: 100 / 0.0 |

资源：C3-F* 的旧 power_kw 字段是抽象预约单位，不是实测 kW；其他组按作者定义参数解释，均未设备校准。
完整合法操作以工具签名、前提和服务匹配为准；off 即使合法也不提供请求服务。

## 权限与可见信息

| 输入 | 主体 | 可见状态 | 可写资源 | 工具 |
|---|---|---|---|---|
| REV-C4-RAIN-NOEVENT-LC2 | IrrigationAgent | garden.soil_moisture_pct, weather.raining | devices.irrigation | start_irrigation |
| REV-C4-RAIN-NOEVENT-LC2 | WeatherAgent | weather.raining | devices.weather_sensor | observe_weather |

上表对字段相同的主体去重；逐输入权限仍以 contracts.json 为准。服务回执由可信执行器写入，不授权主体直接写评分字段。

## 初态、容量与外源事件

### REV-C4-RAIN-NOEVENT-LC2

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 117,
    "values": {
      "garden": {
        "soil_moisture_pct": 20
      },
      "weather": {
        "raining": false
      },
      "devices": {
        "irrigation": "off",
        "weather_sensor": "idle"
      },
      "service": {
        "work_completed": false,
        "monitor_completed": false
      },
      "diagnostic": {
        "heartbeat": 0
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100,
    "lifecycle_contracts": {
      "water_garden": {
        "mode": "withdraw",
        "valid_when": [
          {
            "path": "weather.raining",
            "op": "eq",
            "value": false
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.irrigation": "off"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "weather.raining",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.irrigation",
          "op": "neq",
          "value": "on"
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.work_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.monitor_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### REV-C4-RAIN-PRESTART-LC2

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 117,
    "values": {
      "garden": {
        "soil_moisture_pct": 20
      },
      "weather": {
        "raining": false
      },
      "devices": {
        "irrigation": "off",
        "weather_sensor": "idle"
      },
      "service": {
        "work_completed": false,
        "monitor_completed": false
      },
      "diagnostic": {
        "heartbeat": 0
      }
    }
  },
  "events": [
    {
      "at_ms": 200,
      "event": "rain_begins",
      "patch": {
        "weather.raining": true
      }
    }
  ],
  "simulation": {
    "command_latency_ms": 100,
    "lifecycle_contracts": {
      "water_garden": {
        "mode": "withdraw",
        "valid_when": [
          {
            "path": "weather.raining",
            "op": "eq",
            "value": false
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.irrigation": "off"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "weather.raining",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.irrigation",
          "op": "neq",
          "value": "on"
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.work_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.monitor_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### REV-C4-RAIN-INFLIGHT-LC2

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 117,
    "values": {
      "garden": {
        "soil_moisture_pct": 20
      },
      "weather": {
        "raining": false
      },
      "devices": {
        "irrigation": "off",
        "weather_sensor": "idle"
      },
      "service": {
        "work_completed": false,
        "monitor_completed": false
      },
      "diagnostic": {
        "heartbeat": 0
      }
    }
  },
  "events": [
    {
      "at_ms": 1000,
      "event": "rain_begins",
      "patch": {
        "weather.raining": true
      }
    }
  ],
  "simulation": {
    "command_latency_ms": 100,
    "lifecycle_contracts": {
      "water_garden": {
        "mode": "withdraw",
        "valid_when": [
          {
            "path": "weather.raining",
            "op": "eq",
            "value": false
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.irrigation": "off"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "weather.raining",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.irrigation",
          "op": "neq",
          "value": "on"
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.work_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.monitor_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### REV-C4-RAIN-POSTCOMPLETE-LC2

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 117,
    "values": {
      "garden": {
        "soil_moisture_pct": 20
      },
      "weather": {
        "raining": false
      },
      "devices": {
        "irrigation": "off",
        "weather_sensor": "idle"
      },
      "service": {
        "work_completed": false,
        "monitor_completed": false
      },
      "diagnostic": {
        "heartbeat": 0
      }
    }
  },
  "events": [
    {
      "at_ms": 4000,
      "event": "rain_begins",
      "patch": {
        "weather.raining": true
      }
    }
  ],
  "simulation": {
    "command_latency_ms": 100,
    "lifecycle_contracts": {
      "water_garden": {
        "mode": "withdraw",
        "valid_when": [
          {
            "path": "weather.raining",
            "op": "eq",
            "value": false
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.irrigation": "off"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "weather.raining",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.irrigation",
          "op": "neq",
          "value": "on"
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.work_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.monitor_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### REV-C4-RAIN-UNRELATED-LC2

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 117,
    "values": {
      "garden": {
        "soil_moisture_pct": 20
      },
      "weather": {
        "raining": false
      },
      "devices": {
        "irrigation": "off",
        "weather_sensor": "idle"
      },
      "service": {
        "work_completed": false,
        "monitor_completed": false
      },
      "diagnostic": {
        "heartbeat": 0
      }
    }
  },
  "events": [
    {
      "at_ms": 1000,
      "event": "heartbeat",
      "patch": {
        "diagnostic.heartbeat": 1
      }
    }
  ],
  "simulation": {
    "command_latency_ms": 100,
    "lifecycle_contracts": {
      "water_garden": {
        "mode": "withdraw",
        "valid_when": [
          {
            "path": "weather.raining",
            "op": "eq",
            "value": false
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.irrigation": "off"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "weather.raining",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.irrigation",
          "op": "neq",
          "value": "on"
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.work_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.monitor_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```
