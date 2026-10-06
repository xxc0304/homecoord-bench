# C1-LIGHT：设计证据卡

状态：待审。仅任务定义，不含运行成绩。完整状态、工具签名、动作效果与约束见 contracts.json 中本组。
任务模板、grounding 和 service 字段为审查者可见的执行/评分合同，不能据此认为全部进入决策者输入。
权限表的 observable_state 才是局部状态视图；公共信息与未来事件另按发布规则限制。

## 请求语义与验收边界

一个阅读保护请求有效至6000ms；相反请求有效期内应拒绝，到期后可执行。这里只判设备状态保护，不判真实照度。

仅有单一保护请求，其他同时使用需求与撤销仲裁未建模；有效期和优先级均为作者假设。不得声称真实照明或多请求仲裁验收。

审查者需判断以上合同能否接受或应修改；它们是当前声明，不是已获批准的事实。

## 输入与配对参数

| 输入 ID | 任务 | 发布 ms | 截止 ms | 合格操作：持续 ms / 资源 |
|---|---|---:|---:|---|
| REV-C1-LIGHT-CONFLICT | reading_light | 0 | 1100 | set_reading: 500 / 0.02 |
| REV-C1-LIGHT-CONFLICT | energy_light | 1200 | 8000 | off: 500 / 0.0 |
| REV-C1-LIGHT-SAFE | reading_light | 0 | 1100 | set_reading: 500 / 0.02 |
| REV-C1-LIGHT-SAFE | energy_light | 6500 | 8000 | off: 500 / 0.0 |

资源：C3-F* 的旧 power_kw 字段是抽象预约单位，不是实测 kW；其他组按作者定义参数解释，均未设备校准。
完整合法操作以工具签名、前提和服务匹配为准；off 即使合法也不提供请求服务。

## 权限与可见信息

| 输入 | 主体 | 可见状态 | 可写资源 | 工具 |
|---|---|---|---|---|
| REV-C1-LIGHT-CONFLICT | ReadingAgent | devices.study_light, study.reading_active | devices.study_light | set_light |
| REV-C1-LIGHT-CONFLICT | EnergyAgent | devices.study_light, study.occupied, study.reading_active | devices.study_light | set_light |

上表对字段相同的主体去重；逐输入权限仍以 contracts.json 为准。服务回执由可信执行器写入，不授权主体直接写评分字段。

## 初态、容量与外源事件

### REV-C1-LIGHT-CONFLICT

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 120,
    "values": {
      "study": {
        "occupied": true,
        "reading_active": true
      },
      "devices": {
        "study_light": "reading"
      },
      "service": {
        "protected": false,
        "lower": false
      }
    }
  },
  "events": [
    {
      "at_ms": 6000,
      "event": "protected_request_expires",
      "patch": {
        "study.reading_active": false
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
          "path": "study.reading_active",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.study_light",
          "op": "neq",
          "value": "off"
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.protected",
      "op": "eq",
      "value": true
    }
  ]
}
```

### REV-C1-LIGHT-SAFE

容量字段：8.0；命令延迟：100 ms。

```json
{
  "initial_state": {
    "version": 120,
    "values": {
      "study": {
        "occupied": true,
        "reading_active": true
      },
      "devices": {
        "study_light": "reading"
      },
      "service": {
        "protected": false,
        "lower": false
      }
    }
  },
  "events": [
    {
      "at_ms": 6000,
      "event": "protected_request_expires",
      "patch": {
        "study.reading_active": false
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
          "path": "study.reading_active",
          "op": "eq",
          "value": true
        }
      ],
      "must": [
        {
          "path": "devices.study_light",
          "op": "neq",
          "value": "off"
        }
      ]
    }
  ],
  "goals": [
    {
      "path": "service.protected",
      "op": "eq",
      "value": true
    }
  ]
}
```
