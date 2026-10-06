# DEPENDENCY：设计证据卡

状态：待审。仅任务定义，不含运行成绩。完整状态、工具签名、动作效果与约束见 contracts.json 中本组。
任务模板、grounding 和 service 字段为审查者可见的执行/评分合同，不能据此认为全部进入决策者输入。
权限表的 observable_state 才是局部状态视图；公共信息与未来事件另按发布规则限制。

## 请求语义与验收边界

dry必须同时满足washed状态与有效wash完成回执。撤回的wash及旧取消尝试不放行；独立第三负载才引入容量因素。

仅单次任务级工作流，尚无实体衣物batch_id；请求/提案ID不等于批次身份。FAILED_WASH需Phase B非法提案注入，源episode除ID等元数据外不是独立结构。

审查者需判断以上合同能否接受或应修改；它们是当前声明，不是已获批准的事实。

## 输入与配对参数

| 输入 ID | 任务 | 发布 ms | 截止 ms | 合格操作：持续 ms / 资源 |
|---|---|---:|---:|---|
| DEP-LAUNDRY-EARLY_REQUEST | wash | 0 | 15000 | wash: 4000 / 1.5 |
| DEP-LAUNDRY-EARLY_REQUEST | dry | 100 | 15000 | dry: 4000 / 2.0 |
| DEP-LAUNDRY-LATE_REQUEST | wash | 0 | 15000 | wash: 4000 / 1.5 |
| DEP-LAUNDRY-LATE_REQUEST | dry | 5000 | 15000 | dry: 4000 / 2.0 |
| DEP-LAUNDRY-TIGHT_DEADLINE | wash | 0 | 15000 | wash: 4000 / 1.5 |
| DEP-LAUNDRY-TIGHT_DEADLINE | dry | 100 | 8000 | dry: 4000 / 2.0 |
| DEP-LAUNDRY-CANCEL_WASH | wash | 0 | 15000 | wash: 4000 / 1.5 |
| DEP-LAUNDRY-CANCEL_WASH | dry | 100 | 15000 | dry: 4000 / 2.0 |
| DEP-LAUNDRY-RESTART_WASH | wash | 0 | 15000 | wash: 4000 / 1.5 |
| DEP-LAUNDRY-RESTART_WASH | dry | 100 | 15000 | dry: 4000 / 2.0 |
| DEP-LAUNDRY-FORGED_STATE | wash | 0 | 15000 | wash: 4000 / 1.5 |
| DEP-LAUNDRY-FORGED_STATE | dry | 100 | 15000 | dry: 4000 / 2.0 |
| DEP-LAUNDRY-FAILED_WASH | wash | 0 | 15000 | wash: 4000 / 1.5 |
| DEP-LAUNDRY-FAILED_WASH | dry | 100 | 15000 | dry: 4000 / 2.0 |
| DEP-LAUNDRY-CAPACITY_TIGHT | wash | 0 | 15000 | wash: 4000 / 1.5 |
| DEP-LAUNDRY-CAPACITY_TIGHT | dry | 100 | 15000 | dry: 4000 / 2.0 |
| DEP-LAUNDRY-CAPACITY_TIGHT | dishes | 0 | 15000 | wash_dishes: 8000 / 1.5 |
| DEP-LAUNDRY-CAPACITY_SAFE | wash | 0 | 15000 | wash: 4000 / 1.5 |
| DEP-LAUNDRY-CAPACITY_SAFE | dry | 100 | 15000 | dry: 4000 / 2.0 |
| DEP-LAUNDRY-CAPACITY_SAFE | dishes | 0 | 15000 | wash_dishes: 8000 / 1.5 |

资源：C3-F* 的旧 power_kw 字段是抽象预约单位，不是实测 kW；其他组按作者定义参数解释，均未设备校准。
完整合法操作以工具签名、前提和服务匹配为准；off 即使合法也不提供请求服务。

## 权限与可见信息

| 输入 | 主体 | 可见状态 | 可写资源 | 工具 |
|---|---|---|---|---|
| DEP-LAUNDRY-EARLY_REQUEST | WasherAgent | laundry.wash_authorized, laundry.washed | devices.washer | start_washer |
| DEP-LAUNDRY-EARLY_REQUEST | DryerAgent | laundry.dry, laundry.wash_authorized, laundry.washed | devices.dryer | start_dryer |
| DEP-LAUNDRY-CAPACITY_TIGHT | DishesAgent | devices.dishwasher | devices.dishwasher | start_dishwasher |

上表对字段相同的主体去重；逐输入权限仍以 contracts.json 为准。服务回执由可信执行器写入，不授权主体直接写评分字段。

## 初态、容量与外源事件

### DEP-LAUNDRY-EARLY_REQUEST

容量字段：6；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 112,
    "values": {
      "laundry": {
        "washed": false,
        "dry": false,
        "wash_authorized": true
      },
      "devices": {
        "washer": "off",
        "dryer": "off"
      },
      "service": {
        "wash_completed": false,
        "dry_completed": false
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100
  },
  "constraints": [
    {
      "when": [
        {
          "path": "devices.dryer",
          "op": "eq",
          "value": "running"
        }
      ],
      "must": [
        {
          "path": "laundry.washed",
          "op": "eq",
          "value": true
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.wash_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.dry_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### DEP-LAUNDRY-LATE_REQUEST

容量字段：6；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 112,
    "values": {
      "laundry": {
        "washed": false,
        "dry": false,
        "wash_authorized": true
      },
      "devices": {
        "washer": "off",
        "dryer": "off"
      },
      "service": {
        "wash_completed": false,
        "dry_completed": false
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100
  },
  "constraints": [
    {
      "when": [
        {
          "path": "devices.dryer",
          "op": "eq",
          "value": "running"
        }
      ],
      "must": [
        {
          "path": "laundry.washed",
          "op": "eq",
          "value": true
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.wash_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.dry_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### DEP-LAUNDRY-TIGHT_DEADLINE

容量字段：6；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 112,
    "values": {
      "laundry": {
        "washed": false,
        "dry": false,
        "wash_authorized": true
      },
      "devices": {
        "washer": "off",
        "dryer": "off"
      },
      "service": {
        "wash_completed": false,
        "dry_completed": false
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100
  },
  "constraints": [
    {
      "when": [
        {
          "path": "devices.dryer",
          "op": "eq",
          "value": "running"
        }
      ],
      "must": [
        {
          "path": "laundry.washed",
          "op": "eq",
          "value": true
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.wash_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.dry_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### DEP-LAUNDRY-CANCEL_WASH

容量字段：6；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 112,
    "values": {
      "laundry": {
        "washed": false,
        "dry": false,
        "wash_authorized": true
      },
      "devices": {
        "washer": "off",
        "dryer": "off"
      },
      "service": {
        "wash_completed": false,
        "dry_completed": false
      }
    }
  },
  "events": [
    {
      "at_ms": 1000,
      "event": "wash_authorization_revoked",
      "patch": {
        "laundry.wash_authorized": false
      }
    }
  ],
  "simulation": {
    "command_latency_ms": 100,
    "lifecycle_contracts": {
      "wash": {
        "mode": "withdraw",
        "valid_when": [
          {
            "path": "laundry.wash_authorized",
            "op": "eq",
            "value": true
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.washer": "off"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "devices.dryer",
          "op": "eq",
          "value": "running"
        }
      ],
      "must": [
        {
          "path": "laundry.washed",
          "op": "eq",
          "value": true
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.wash_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.dry_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### DEP-LAUNDRY-RESTART_WASH

容量字段：6；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 112,
    "values": {
      "laundry": {
        "washed": false,
        "dry": false,
        "wash_authorized": true
      },
      "devices": {
        "washer": "off",
        "dryer": "off"
      },
      "service": {
        "wash_completed": false,
        "dry_completed": false
      }
    }
  },
  "events": [
    {
      "at_ms": 1000,
      "event": "wash_authorization_revoked",
      "patch": {
        "laundry.wash_authorized": false
      }
    },
    {
      "at_ms": 5000,
      "event": "wash_authorization_restored",
      "patch": {
        "laundry.wash_authorized": true
      }
    }
  ],
  "simulation": {
    "command_latency_ms": 100,
    "lifecycle_contracts": {
      "wash": {
        "mode": "restart_from_zero",
        "valid_when": [
          {
            "path": "laundry.wash_authorized",
            "op": "eq",
            "value": true
          }
        ],
        "stop_ack_delay_ms": 200,
        "restart_delay_ms": 0,
        "stop_effects": {
          "devices.washer": "off"
        }
      }
    }
  },
  "constraints": [
    {
      "when": [
        {
          "path": "devices.dryer",
          "op": "eq",
          "value": "running"
        }
      ],
      "must": [
        {
          "path": "laundry.washed",
          "op": "eq",
          "value": true
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.wash_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.dry_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### DEP-LAUNDRY-FORGED_STATE

容量字段：6；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 112,
    "values": {
      "laundry": {
        "washed": false,
        "dry": false,
        "wash_authorized": true
      },
      "devices": {
        "washer": "off",
        "dryer": "off"
      },
      "service": {
        "wash_completed": false,
        "dry_completed": false
      }
    }
  },
  "events": [
    {
      "at_ms": 450,
      "event": "untrusted_state_patch",
      "patch": {
        "laundry.washed": true
      }
    }
  ],
  "simulation": {
    "command_latency_ms": 100
  },
  "constraints": [
    {
      "when": [
        {
          "path": "devices.dryer",
          "op": "eq",
          "value": "running"
        }
      ],
      "must": [
        {
          "path": "laundry.washed",
          "op": "eq",
          "value": true
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.wash_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.dry_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### DEP-LAUNDRY-FAILED_WASH

容量字段：6；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 112,
    "values": {
      "laundry": {
        "washed": false,
        "dry": false,
        "wash_authorized": true
      },
      "devices": {
        "washer": "off",
        "dryer": "off"
      },
      "service": {
        "wash_completed": false,
        "dry_completed": false
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100
  },
  "constraints": [
    {
      "when": [
        {
          "path": "devices.dryer",
          "op": "eq",
          "value": "running"
        }
      ],
      "must": [
        {
          "path": "laundry.washed",
          "op": "eq",
          "value": true
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.wash_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.dry_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### DEP-LAUNDRY-CAPACITY_TIGHT

容量字段：3；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 112,
    "values": {
      "laundry": {
        "washed": false,
        "dry": false,
        "wash_authorized": true
      },
      "devices": {
        "washer": "off",
        "dryer": "off",
        "dishwasher": "off"
      },
      "service": {
        "wash_completed": false,
        "dry_completed": false,
        "dishes_completed": false
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100
  },
  "constraints": [
    {
      "when": [
        {
          "path": "devices.dryer",
          "op": "eq",
          "value": "running"
        }
      ],
      "must": [
        {
          "path": "laundry.washed",
          "op": "eq",
          "value": true
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.wash_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.dry_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```

### DEP-LAUNDRY-CAPACITY_SAFE

容量字段：6；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 112,
    "values": {
      "laundry": {
        "washed": false,
        "dry": false,
        "wash_authorized": true
      },
      "devices": {
        "washer": "off",
        "dryer": "off",
        "dishwasher": "off"
      },
      "service": {
        "wash_completed": false,
        "dry_completed": false,
        "dishes_completed": false
      }
    }
  },
  "events": [],
  "simulation": {
    "command_latency_ms": 100
  },
  "constraints": [
    {
      "when": [
        {
          "path": "devices.dryer",
          "op": "eq",
          "value": "running"
        }
      ],
      "must": [
        {
          "path": "laundry.washed",
          "op": "eq",
          "value": true
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.wash_completed",
      "op": "eq",
      "value": true
    },
    {
      "path": "service.dry_completed",
      "op": "eq",
      "value": true
    }
  ]
}
```
