# MapFinBen 赛事介绍

<p align="center">
<img src=.github/images/logo.png >
</p>

## 框架介绍

跨主流与低资源语言对齐的大模型金融评测 MapFinBen，是一个面向多语言金融场景的大语言模型评测框架。该框架聚焦英语、中文等主流高资源金融语言与低资源金融语言之间的能力差距，旨在系统评估大语言模型在跨语言、跨资源条件下的金融文本理解、推理、分类与生成能力。

MapFinBen 覆盖金融选择问答、金融文本问答、金融情感分析、金融主题分类和金融文本摘要五类典型任务，涵盖英语、中文、印度尼西亚语、西班牙语、希腊语和日语等多种语言，共构建 30 个数据集、63,064 条样本。通过统一的数据格式、任务设置和评价标准，MapFinBen 为多语言金融大模型的能力比较、问题诊断和技术改进提供了可复现、可扩展的评测基准。

## 任务简介

金融文本具有专业术语密集、语义依赖强、推理链条复杂和领域风险敏感等特点。相比通用自然语言处理任务，金融场景不仅要求模型理解文本表层含义，还需要具备金融知识、数值敏感性、跨语言迁移能力和本地化语境理解能力。尤其在低资源语言环境下，金融语料和标注数据相对稀缺，模型往往难以充分捕捉不同语言中的金融术语表达、市场文化差异和业务语境。

MapFinBen 任务旨在从多种金融任务角度评估大语言模型的综合金融能力，包括信息理解、问答推理、情绪识别、主题归纳和摘要生成等方面：

- 金融选择问答（MapFinAS）：给定金融领域问题及候选选项，模型需要选择最合适的答案，评估其金融知识理解、上下文推理和选项判别能力。
- 金融文本问答（MapFinQA）：给定金融文本和相关问题，模型需要从文本中提取关键信息并生成准确答案，考察其阅读理解、信息抽取和金融推理能力。
- 金融情感分析（MapFinSA）：给定金融新闻、评论或报告文本，模型需要判断其情感倾向，如积极、中性或消极，评估其对金融市场情绪和语义细微差别的识别能力。
- 金融主题分类（MapFinTC）：给定金融文本，模型需要判断其所属主题类别，考察模型对金融文本结构、主题边界和业务语义的分类能力。
- 金融文本摘要（MapFinTS）：给定较长金融文本，模型需要生成保留核心信息的摘要，评估其信息压缩、重点提取和金融语义保持能力。

通过上述五类任务，MapFinBen 能够全面评估大语言模型在主流语言与低资源语言金融场景中的泛化能力、公平性和鲁棒性。

## 提交事项

（1）请参赛的选手将参加评测的大语言模型的完整文件提交到huggingface，确保模型文件格式为safetensor。

（2）提交submit.txt文件，文件内容为huggingface上的模型ID，例如，对于链接https://huggingface.co/Qwen/Qwen3-8B，ID为Qwen/Qwen3-8B

（3）每支参赛队伍在测试集上的正式评测提交次数不超过 2 次，对于第二次之后的提交将不会进行评测，最终排名以有效提交结果为准。

（4）参评模型参数规模需控制在 10B 以内。

### 模型规模检查代码

参赛队伍可使用以下脚本检查模型参数规模是否满足 10B 以内的限制。脚本通过空权重初始化统计参数量，不会完整加载模型权重。

```python
# check_model_size.py
import argparse

from accelerate import init_empty_weights
from transformers import AutoConfig, AutoModelForCausalLM, PretrainedConfig
from transformers.models.auto.configuration_auto import CONFIG_MAPPING


MAX_PARAMS = 10_000_000_000


def load_model_config(model_name_or_path: str, trust_remote_code: bool = False):
    try:
        return AutoConfig.from_pretrained(
            model_name_or_path,
            trust_remote_code=trust_remote_code,
        )
    except ValueError as error:
        if "rope_scaling" not in str(error):
            raise

        print("检测到 rope_scaling 配置与当前 transformers 版本不兼容，已自动使用兼容配置进行参数量统计。")
        config_dict, _ = PretrainedConfig.get_config_dict(
            model_name_or_path,
            trust_remote_code=trust_remote_code,
        )

        rope_scaling = config_dict.get("rope_scaling")
        if not isinstance(rope_scaling, dict) or "factor" not in rope_scaling:
            raise

        rope_type = rope_scaling.get("type") or rope_scaling.get("rope_type") or "dynamic"
        if rope_type not in {"linear", "dynamic"}:
            # 该字段不影响参数量统计；旧版 transformers 只接受 linear/dynamic。
            rope_type = "dynamic"
        config_dict["rope_scaling"] = {
            "type": rope_type,
            "factor": float(rope_scaling["factor"]),
        }

        model_type = config_dict.get("model_type")
        if model_type not in CONFIG_MAPPING:
            raise ValueError(f"无法识别模型类型：{model_type}。请升级 transformers 后重试。") from error
        return CONFIG_MAPPING[model_type].from_dict(config_dict)


def count_model_params(model_name_or_path: str, trust_remote_code: bool = False) -> int:
    config = load_model_config(model_name_or_path, trust_remote_code)
    with init_empty_weights():
        model = AutoModelForCausalLM.from_config(
            config,
            trust_remote_code=trust_remote_code,
        )
    return sum(parameter.numel() for parameter in model.parameters())


def main() -> None:
    parser = argparse.ArgumentParser(description="检查模型参数规模是否满足 MapFinBen 10B 以内的限制。")
    parser.add_argument("--model", required=True, help="本地模型路径或 Hugging Face 模型 ID。")
    parser.add_argument("--trust_remote_code", action="store_true", help="如模型需要执行自定义代码，请启用该参数。")
    args = parser.parse_args()
    
    print(f"模型规模检测开始，模型路径：{args.model}")
    try:
        total_params = count_model_params(args.model, args.trust_remote_code)
    except Exception as error:
        raise SystemExit(f"检测失败：{error}") from error
    total_params_b = total_params / 1_000_000_000

    print(f"模型参数量：{total_params:,}（{total_params_b:.3f}B）")
    if total_params > MAX_PARAMS:
        raise SystemExit("未通过")
    print("通过")


if __name__ == "__main__":
    main()
```

使用方式如下：

```bash
pip install transformers accelerate
python check_model_size.py --model /path/to/model
python check_model_size.py --model Qwen/Qwen3-8B --trust_remote_code
```

## 赛事安排

### 赛程 UTC+8

2026 年 2 月 1 日：评测任务报名开始；

2026 年 3 月 15 日：CCL26 宣传发布；

2026 年 5 月-6 月：各报名参赛队开展技术评测；

2026 年 6 月 29 日：测试集结果提交截止；

2026 年 6 月 30 日：评测任务结束，公布参赛队伍成绩和排名；

2026 年 7 月 10 日：提交中文或英文技术报告；

2026 年 7 月 25 日：评测论文审稿与录用通知；

2026 年 8 月 15 日：评测论文 Camera-ready 版提交；

2026 年 9 月 15 日：评测论文纠错排版并提交 ACL/CCL Anthology 收录；

2026 年 10 月：CCL 2026 技术评测研讨会。

## 参赛规则

1. 本评测面向全社会开放，个人、高等院校、科研单位、企业及人工智能研究机构等人员均可报名参赛。
2. 参赛队伍需按照组委会要求完成报名和数据申请，确保报名信息真实、准确、有效。
3. 参赛者应仅将评测数据用于本次评测及相关科学研究，不得用于任何未经授权的商业用途或其他应用场景。
4. 参评模型参数规模需控制在 10B 以内。
5. 每支参赛队伍在测试集上的正式评测提交次数不超过 2 次，严禁使用多个账号重复提交、刷榜或规避提交限制；如发现异常提交行为，组委会有权取消相关成绩或参赛资格。
6. 严禁参赛者之间相互抄袭结果、代码、模型或技术方案。如不同队伍提交结果高度相似且经判定存在违规行为，相关成绩将被视为无效。
7. 参赛者不得通过修改评测源代码、篡改测试数据、泄露测试集答案等方式作弊，一经发现将取消参赛资格。
8. 参赛者应保证其在评测过程中产出的模型、代码、报告和其他研究成果不侵犯任何第三方知识产权、商业秘密及其他合法权益。
9. 在评测期间，未经组委会许可，参赛者不得公开传播未公开的测试数据、答案、评测脚本或其他受限材料。
10. 参赛队伍提交的技术报告和评测结果可在注明来源后用于评测总结、论文发表、榜单展示和学术交流。
11. 最终排名按照五个任务得分的平均值计算，各任务得分由对应评价指标综合得到。

## 组织者

评测组织者：胡刚、岳昆（云南大学），彭敏（武汉大学），石磊（云南师范大学）

任务联系人：孔晓勇，云南大学硕士研究生

联系邮箱：kongxiaoyong@stu.ynu.edu.cn

## 团队成员

研究生：王情情、张群、陈雅婷、张群、韦甜、陈雅婷

本科生：秦一鸣、吕思齐、王振旭、赵爱嘉、蒋亿乐

## 任务网址

项目主页：https://github.com/MapFinBen/MapFinBen

## 评测答疑

<p align="center">
  <img src=".github/images/qrcode.png" width="800"/>
</p>
