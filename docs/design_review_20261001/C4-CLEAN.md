# C4-CLEAN：设计证据卡

状态：待审。仅任务定义，不含运行成绩。完整状态、工具签名、动作效果与约束见 contracts.json 中本组。
任务模板、grounding 和 service 字段为审查者可见的执行/评分合同，不能据此认为全部进入决策者输入。
权限表的 observable_state 才是局部状态视图；公共信息与未来事件另按发布规则限制。

## 请求语义与验收边界

空置时才能执行清洁；占用变真请求停止，确认后才停止并释放资源；空置恢复后从零执行完整新尝试。

200ms确认、从零恢复均为合成合同；第二主体只提供独立服务，不证明协调必要。未模拟检测滞后；事件时刻即执行器获知时刻。

审查者需判断以上合同能否接受或应修改；它们是当前声明，不是已获批准的事实。

## 输入与配对参数

| 输入 ID | 任务 | 发布 ms | 截止 ms | 合格操作：持续 ms / 资源 |
|---|---|---:|---:|---|
| REV-C4-CLEAN-NOEVENT-LC2 | bedroom_clean | 0 | 10000 | clean: 3000 / 0.2 |
| REV-C4-CLEAN-NOEVENT-LC2 | bedroom_occupancy | 0 | 2000 | observe: 100 / 0.0 |
| REV-C4-CLEAN-PRESTART-LC2 | bedroom_clean | 0 | 10000 | clean: 3000 / 0.2 |
| REV-C4-CLEAN-PRESTART-LC2 | bedroom_occupancy | 0 | 2000 | observe: 100 / 0.0 |
| REV-C4-CLEAN-INFLIGHT-LC2 | bedroom_clean | 0 | 10000 | clean: 3000 / 0.2 |
| REV-C4-CLEAN-INFLIGHT-LC2 | bedroom_occupancy | 0 | 2000 | observe: 100 / 0.0 |
| REV-C4-CLEAN-POSTCOMPLETE-LC2 | bedroom_clean | 0 | 10000 | clean: 3000 / 0.2 |
| REV-C4-CLEAN-POSTCOMPLETE-LC2 | bedroom_occupancy | 0 | 2000 | observe: 100 / 0.0 |
| REV-C4-CLEAN-UNRELATED-LC2 | bedroom_clean | 0 | 10000 | clean: 3000 / 0.2 |
| REV-C4-CLEAN-UNRELATED-LC2 | bedroom_occupancy | 0 | 2000 | observe: 100 / 0.0 |

资源：C3-F* 的旧 power_kw 字段是抽象预约单位，不是实测 kW；其他组按作者定义参数解释，均未设备校准。
完整合法操作以工具签名、前提和服务匹配为准；off 即使合法也不提供请求服务。

## 权限与可见信息

| 输入 | 主体 | 可见状态 | 可写资源 | 工具 |
|---|---|---|---|---|
| REV-C4-CLEAN-NOEVENT-LC2 | BedroomCleaningAgent | bedroom.occupied | devices.bedroom_robot | start_robot |
| REV-C4-CLEAN-NOEVENT-LC2 | BedroomCareAgent | bedroom.occupied | devices.occupancy_sensor | observe_occupancy |

上表对字段相同的主体去重；逐输入权限仍以 contracts.json 为准。服务回执由可信执行器写入，不授权主体直接写评分字段。

## 初态、容量与外源事件

### REV-C4-CLEAN-NOEVENT-LC2

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 116,
    "values": {
      "bedroom": {
        "occupied": false,
        "clean": false
      },
      "devices": {
        "bedroom_robot": "idle",
        "occupancy_sensor": "idle"
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
      "bedroom_clean": {
        "mode": "restart_from_zero",
        "valid_when": [
          {
            "path": "bedroom.occupied",
            "op": "eq",
            "value": false
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.bedroom_robot": "idle"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "bedroom.occupied",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.bedroom_robot",
          "op": "neq",
          "value": "running"
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

### REV-C4-CLEAN-PRESTART-LC2

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 116,
    "values": {
      "bedroom": {
        "occupied": false,
        "clean": false
      },
      "devices": {
        "bedroom_robot": "idle",
        "occupancy_sensor": "idle"
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
      "event": "resident_enters",
      "patch": {
        "bedroom.occupied": true
      }
    },
    {
      "at_ms": 5000,
      "event": "resident_leaves",
      "patch": {
        "bedroom.occupied": false
      }
    }
  ],
  "simulation": {
    "command_latency_ms": 100,
    "lifecycle_contracts": {
      "bedroom_clean": {
        "mode": "restart_from_zero",
        "valid_when": [
          {
            "path": "bedroom.occupied",
            "op": "eq",
            "value": false
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.bedroom_robot": "idle"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "bedroom.occupied",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.bedroom_robot",
          "op": "neq",
          "value": "running"
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

### REV-C4-CLEAN-INFLIGHT-LC2

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 116,
    "values": {
      "bedroom": {
        "occupied": false,
        "clean": false
      },
      "devices": {
        "bedroom_robot": "idle",
        "occupancy_sensor": "idle"
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
      "event": "resident_enters",
      "patch": {
        "bedroom.occupied": true
      }
    },
    {
      "at_ms": 5000,
      "event": "resident_leaves",
      "patch": {
        "bedroom.occupied": false
      }
    }
  ],
  "simulation": {
    "command_latency_ms": 100,
    "lifecycle_contracts": {
      "bedroom_clean": {
        "mode": "restart_from_zero",
        "valid_when": [
          {
            "path": "bedroom.occupied",
            "op": "eq",
            "value": false
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.bedroom_robot": "idle"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "bedroom.occupied",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.bedroom_robot",
          "op": "neq",
          "value": "running"
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

### REV-C4-CLEAN-POSTCOMPLETE-LC2

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 116,
    "values": {
      "bedroom": {
        "occupied": false,
        "clean": false
      },
      "devices": {
        "bedroom_robot": "idle",
        "occupancy_sensor": "idle"
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
      "event": "resident_enters",
      "patch": {
        "bedroom.occupied": true
      }
    },
    {
      "at_ms": 5000,
      "event": "resident_leaves",
      "patch": {
        "bedroom.occupied": false
      }
    }
  ],
  "simulation": {
    "command_latency_ms": 100,
    "lifecycle_contracts": {
      "bedroom_clean": {
        "mode": "restart_from_zero",
        "valid_when": [
          {
            "path": "bedroom.occupied",
            "op": "eq",
            "value": false
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.bedroom_robot": "idle"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "bedroom.occupied",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.bedroom_robot",
          "op": "neq",
          "value": "running"
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

### REV-C4-CLEAN-UNRELATED-LC2

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 116,
    "values": {
      "bedroom": {
        "occupied": false,
        "clean": false
      },
      "devices": {
        "bedroom_robot": "idle",
        "occupancy_sensor": "idle"
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
      "bedroom_clean": {
        "mode": "restart_from_zero",
        "valid_when": [
          {
            "path": "bedroom.occupied",
            "op": "eq",
            "value": false
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.bedroom_robot": "idle"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "bedroom.occupied",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.bedroom_robot",
          "op": "neq",
          "value": "running"
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
