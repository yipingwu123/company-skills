---
name: excel-transform
description: 处理 Excel/CSV 的筛选、匹配、汇总、去重、模板填充和本地校验；优先用脚本完成，减少 AI token 消耗。
version: 0.1.0
metadata:
  cn_name: Excel处理
  stage: dry-run
  tags: [excel, csv, transform, report, dry-run]
---

# Excel处理

## 这个 skill 是做什么的

把可确定的表格处理逻辑脚本化，例如筛选日期、按号码匹配、汇总多个任务结果、填充导入模板。

## 什么时候用

- 火山结果导出后，需要按号码匹配意向等级、客户标签、通话状态、拨打时间。
- 迈鲸商机导入前，需要生成导入模板。
- 订客多导出后，需要校验日期列是否符合目标日期。
- 看板类流程需要汇总多个 Excel。

## 输入

| 字段 | 说明 |
|---|---|
| source_files | 源 Excel/CSV 文件 |
| transform_config | 筛选、匹配、汇总规则 |
| output_path | 输出文件路径 |

## 输出

| 文件 | 说明 |
|---|---|
| outputs/transformed.xlsx | 转换后的结果 |
| logs/run.log | 中文处理日志 |
| evidence/validation_report.json | 校验结果 |

## 脚本入口

校验 CSV/XLSX 文件：

```bash
python3 common/Excel处理-excel-transform/excel_validator.py \
  --file outputs/exported.csv \
  --config common/Excel处理-excel-transform/examples/validation_config.dingkeduo.json \
  --out evidence/validation_report.json
```

配置示例：

```json
{
  "required_columns": ["呼叫时间", "电话客服", "线路状态"],
  "date_column": "呼叫时间",
  "allowed_dates": ["2026-05-13"],
  "default_year": 2026,
  "min_rows": 1,
  "non_empty_columns": ["呼叫时间", "电话客服"],
  "unique_columns": []
}
```

当前支持：

1. CSV。
2. 常见 XLSX 的第一个工作表。
3. 必要列校验。
4. 日期范围校验。
5. 行数上下限校验。
6. 非空列校验。
7. 重复值提示。

## 人工确认规则

以下情况必须人工确认：

1. 源文件缺少必要列。
2. 日期列存在目标日期之外的数据。
3. 匹配率低于预设阈值。
4. 输出行数和预期差异明显。
5. 即将把结果导入真实系统。

## 失败时怎么定位

查看：

```text
logs/run.log
evidence/validation_report.json
outputs/
```

## 可恢复点

本 skill 只处理本地文件。失败后修正输入文件或配置，再从当前表格处理步骤继续。
