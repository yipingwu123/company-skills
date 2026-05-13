---
name: feishu-requirement-parser
description: 从飞书消息或人工粘贴文本中解析城市、区县、品类等自动化需求字段；字段缺失或模糊时生成中文确认问题。
version: 0.1.0
metadata:
  cn_name: 需求解析
  stage: dry-run
  tags: [feishu, requirement, parser, dry-run]
---

# 需求解析

## 这个 skill 是做什么的

从飞书发给 agent 的消息中提取自动化所需字段，主要包括城市、区县、品类、时间和特殊说明。

## 什么时候用

- 收到“筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐”这类消息时。
- 需要先判断需求是否完整，再进入下一步自动化时。
- 需求格式不固定，需要把自然语言整理成结构化 JSON 时。

## 输入

| 字段 | 说明 |
|---|---|
| requirement_text | 飞书消息原文或人工粘贴文本 |
| known_cities | 可选，已知城市列表 |
| known_districts | 可选，已知区县列表 |
| known_categories | 可选，已知品类列表 |

## 输出

```json
{
  "city": "长沙市",
  "districts": ["岳麓区"],
  "categories": ["餐饮", "休闲娱乐"],
  "missing_fields": [],
  "needs_human_review": false,
  "questions": []
}
```

## 脚本入口

```bash
python3 common/需求解析-feishu-requirement-parser/parse_requirement.py \
  --text "筛选一下长沙市-岳麓区的数据 品类：餐饮，休闲娱乐"
```

## 词库配置

城市、区县、品类、模糊词放在：

```text
common/需求解析-feishu-requirement-parser/vocabulary.json
```

后续新增城市、区县、品类时，优先改词库，不改脚本逻辑。

## 人工确认规则

以下情况必须人工确认：

1. 城市缺失。
2. 区县缺失，且没有明确默认规则。
3. 品类缺失或品类不在已知列表中。
4. 同一句话中出现多个可能冲突的城市、区县或品类。
5. 出现“先跑一批”“按之前的来”等需要上下文的表达。

## 失败时怎么定位

查看：

```text
input/requirement.txt
input/parsed_requirement.json
logs/run.log
```

## 可恢复点

本 skill 不修改外部系统。失败后可以直接修改 `input/requirement.txt` 或补充人工确认结果，再重新解析。
