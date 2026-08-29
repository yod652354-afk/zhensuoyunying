"""实验统计：两比例 z 检验 + 95% 置信区间 + 方向性信号标记（规格 9.2 实验纪律）。

样本不足时标记"方向性信号"，不夸大统计结论。
"""
import math


def two_proportion_ztest(n1: int, rate1: float, n2: int, rate2: float):
    """z 检验：n1/rate1 = treatment，n2/rate2 = control。返回 (z, p_value)。"""
    if n1 <= 0 or n2 <= 0:
        return 0.0, 1.0
    p1, p2 = rate1, rate2
    pooled = (p1 * n1 + p2 * n2) / (n1 + n2)
    if pooled <= 0 or pooled >= 1:
        return 0.0, 1.0
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    # 双尾 p 值（标准正态近似）
    p_value = 2 * (1 - _normal_cdf(abs(z)))
    return z, p_value


def _normal_cdf(x: float) -> float:
    """标准正态累积分布（Abramowitz & Stegun 近似）。"""
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    d = 0.3989423 * math.exp(-x * x / 2)
    poly = ((((1.330274429 * t - 1.821255978) * t + 1.781477937) * t - 0.356563782) * t + 0.319381530) * t
    cdf = 1 - d * poly
    return cdf if x >= 0 else 1 - cdf


def proportion_ci(n: int, rate: float, z: float = 1.96):
    """Wald 置信区间。"""
    if n <= 0:
        return None, None
    se = math.sqrt(rate * (1 - rate) / n) if 0 < rate < 1 else 0.0
    return max(0.0, rate - z * se), min(1.0, rate + z * se)


def experiment_significance(n_t: int, rate_t: float, n_c: int, rate_c: float) -> dict:
    """返回显著性结论与方向性信号标记。"""
    z, p = two_proportion_ztest(n_t, rate_t, n_c, rate_c)
    lo_t, hi_t = proportion_ci(n_t, rate_t)
    lo_c, hi_c = proportion_ci(n_c, rate_c)
    lift = rate_t - rate_c
    min_n = 10  # 样本下限：低于则只给方向性结论
    if n_t < min_n or n_c < min_n:
        conclusion = "directional"   # 方向性信号
        confidence = "样本不足，仅作方向性参考"
    elif p < 0.05:
        conclusion = "significant"
        confidence = f"p={p:.4f} < 0.05，差异显著"
    elif p < 0.10:
        conclusion = "marginal"
        confidence = f"p={p:.4f}，边缘显著"
    else:
        conclusion = "not_significant"
        confidence = f"p={p:.4f}，未达显著"
    return {
        "z": round(z, 4),
        "p_value": round(p, 4),
        "lift_pp": round(lift * 100, 2),
        "ci_treatment": [round(lo_t * 100, 2) if lo_t is not None else None,
                         round(hi_t * 100, 2) if hi_t is not None else None],
        "ci_control": [round(lo_c * 100, 2) if lo_c is not None else None,
                       round(hi_c * 100, 2) if hi_c is not None else None],
        "conclusion": conclusion,
        "confidence": confidence,
    }