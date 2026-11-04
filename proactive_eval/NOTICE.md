# Dataset attribution and handling

Only the dataset versions and files listed in [`dataset-registry.json`](dataset-registry.json) are in scope. Raw files are downloaded into gitignored storage and are not included in commits, releases, prompts shared outside the local evaluator, or public evidence artifacts.

| Dataset | Pinned source | Declared license | Handling note |
| --- | --- | --- | --- |
| When2Speak | [duke-trust-lab/When2Speak](https://huggingface.co/datasets/duke-trust-lab/When2Speak) | CC BY 4.0 | Attribute Duke Trust Lab and preserve the pinned revision. Token and dialogue configurations share contexts and are not independent samples. |
| PITCH | [Social Futures Lab PITCH](https://github.com/Social-Futures-Lab/pitch) | MIT | Preserve the pinned repository LICENSE; timing labels are turn windows. |
| Social AI Ambient Bench | [text-ai/social-ai-ambient-bench](https://huggingface.co/datasets/text-ai/social-ai-ambient-bench) | Apache 2.0 | Use as a tool-assistant interruption diagnostic, not Stella's final social-persona gold. |
| ChMap-Data | [FrontierLab/ChMap-Data](https://huggingface.co/datasets/FrontierLab/ChMap-Data) | Apache 2.0 | Keep each official configuration and task split separate. |
| MemUse | [RuiSumida/memuse](https://huggingface.co/datasets/RuiSumida/memuse) | CC BY-NC 4.0 | Non-commercial terms apply; retain user and matched positive/negative pairing. |
| LoCoMo | [snap-research/locomo](https://github.com/snap-research/locomo) | CC BY-NC 4.0 | Retain the inherited license and do not redistribute raw conversations. |
| PersonaMem-v2 | [bowen-upenn/PersonaMem-v2](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2) | CC BY 4.0 | Attribute the source; the existing adapter output is an external retrieval reference, not an official precision result. |

LoCoMo-Conv, LongMemEval, LiveChat, IRC, MPDD, ishiki multi-party dialogue, and OP-Bench remain blocked or deferred as recorded in the registry. No license is inferred from a paper citation alone.
