"""主动发言频率密度函数。"""

from math import exp


def compute_trigger_probability(
    *,
    global_frequency: float,
    target_frequency: float,
    source_frequency: float,
    quiet_factor: float,
    elapsed_seconds: float,
    base_interval_seconds: float,
    min_interval_seconds: float,
    max_probability: float,
    intent_score: float,
) -> float:
    """计算自动主动发起概率。

    频率配置表达聊天密度，而不是简单次数上限。结果会先受硬间隔约束，再按指数分布累积概率，
    最后乘以 LLM 给出的 intent_score。
    """

    normalized_elapsed = max(0.0, float(elapsed_seconds))
    if normalized_elapsed < max(0.0, float(min_interval_seconds)):
        return 0.0

    effective_frequency = (
        max(0.0, float(global_frequency))
        * max(0.0, float(target_frequency))
        * max(0.0, float(source_frequency))
        * max(0.0, float(quiet_factor))
    )
    if effective_frequency <= 0:
        return 0.0

    normalized_base_interval = max(1.0, float(base_interval_seconds))
    expected_interval = normalized_base_interval / effective_frequency
    raw_probability = 1 - exp(-normalized_elapsed / expected_interval)
    capped_probability = min(max(0.0, raw_probability), max(0.0, float(max_probability)))
    normalized_intent_score = min(1.0, max(0.0, float(intent_score)))
    return capped_probability * normalized_intent_score


def get_source_frequency(source: str, frequency_config: object) -> float:
    """读取指定 source 的密度倍率。"""

    attr_name = f"{source}_source_frequency"
    if source == "self_reflection":
        attr_name = "self_reflection_source_frequency"
    return float(getattr(frequency_config, attr_name, 0.0))

