# 火山外呼任务创建 volcengine-call-task-create

## 用途

根据迈鲸导出并按品类分割的客户文件，在火山引擎智能外呼控制台创建外呼任务。

## 前置条件

1. 已完成火山引擎登录，有 `volcengine_auth_context.json`
2. 已完成迈鲸导出，有按品类分割的 xlsx 文件
3. 人工已确认任务参数

## 步骤状态机

| 步骤 ID | 步骤名称 | 状态 |
|---|---|---|
| load_script_map | 加载品类话术映射 | not_started |
| read_export_file | 读取导出文件 | not_started |
| build_phone_list | 构建手机号列表 | not_started |
| generate_task_plan | 生成任务创建计划 | not_started |
| write_confirmation | 写入人工确认清单 | not_started |
| validate_human_confirmation | 校验人工确认 | not_started |
| create_volcengine_task | 调用 CreateTask API | not_started |
| verify_task_created | 验证任务已创建 | not_started |

## 品类与话术映射

见 `script_map.json`。已验证于 2026-05-13。

| 品类 | 话术名 | Script ID |
|---|---|---|
| 餐饮 | 餐饮 | llm_fgzo_bifje |
| 休闲娱乐 | 休娱和其他 | llm_divs_bigai |
| 购物 | 购物 | llm_mzsi_bigba |
| 丽人 | 丽人 | llm_khrs_bifjj |

## API 信息

```
POST /console/api/v2/call/proxy/bytebot/cn-north-1/2023-01-01/CreateTask
鉴权：X-Csrf-Token header
```

## 文件结构

```text
runs/YYYY-MM-DD/volcengine-call-task-create-品类-批次/
  input/
    human_confirmation.json       # 人工确认后填写
  state/
    run_state.json
  outputs/
    task_plan.json                # 任务参数计划
    phone_list_summary.json       # 手机号摘要（脱敏）
    confirmation_checklist.md     # 人工确认清单
    created_task.json             # 创建成功后的 TaskId
  evidence/
    api_responses/
      create_task_result.json     # API 响应摘要
  logs/run.log
```

## 用法

dry-run 生成计划：

```bash
python3 workflows/火山外呼任务创建-volcengine-call-task-create/create_task_dry_run.py \
  --export-file runs/YYYY-MM-DD/.../outputs/category_餐饮.xlsx \
  --category 餐饮 \
  --task-date 2026-05-14 \
  --number-pool 塔外 \
  --batch 001
```

真实创建（需人工确认）：

```bash
python3 workflows/火山外呼任务创建-volcengine-call-task-create/create_task_dry_run.py \
  --export-file ... \
  --category 餐饮 \
  --task-date 2026-05-14 \
  --number-pool 塔外 \
  --auth-context runs/YYYY-MM-DD/volcengine-login-.../outputs/volcengine_auth_context.json \
  --confirmation-json runs/YYYY-MM-DD/volcengine-call-task-create-.../input/human_confirmation.json \
  --execute-create \
  --batch 001
```

## 侦查结论

见 `login/火山登录-volcengine-login/RECON_FINDINGS.md`
