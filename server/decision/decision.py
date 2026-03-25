from mcp.server.fastmcp import FastMCP
import json
import logging
import os
import re
from typing import Any, Optional

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - graceful fallback if SDK is unavailable
    OpenAI = None

mcp = FastMCP("decision")
logger = logging.getLogger(__name__)

ACTION_LABEL_MAP = {
    "IRRIGATE_NOW": "立即灌溉",
    "RECHECK_SOON": "先复查后决定",
    "MONITOR_ONLY": "先观察不灌溉",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return default


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None

    content = text.strip()
    with_json = None
    try:
        with_json = json.loads(content)
        if isinstance(with_json, dict):
            return with_json
    except Exception:
        pass

    blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
    for block in blocks:
        try:
            obj = json.loads(block.strip())
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue

    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(content[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            return None
    return None


def _build_llm_messages(context: dict) -> list[dict]:
    system_prompt = (
        "你是灌溉决策专家。请基于输入数据做综合判断，优先农业常识和上下文，"
        "不要机械使用固定阈值规则。你可以给出“立即灌溉 / 先复查后决定 / 先观察不灌溉”。"
        "输出必须是纯 JSON，不要额外文本。"
    )

    user_prompt = (
        "请根据以下数据输出 JSON 决策。\n"
        f"输入数据: {json.dumps(context, ensure_ascii=False)}\n\n"
        "JSON 字段要求:\n"
        "{\n"
        '  "decision": {\n'
        '    "irrigate": true/false,\n'
        '    "irrigation_amount_mm": number,\n'
        '    "irrigation_duration_min": number,\n'
        '    "irrigation_time_window": "立即/今天傍晚低蒸发时段/N/A",\n'
        '    "strategy_type": "LLM_REASONED",\n'
        '    "control_mode": "大模型综合判断 + 轻量兜底校验",\n'
        '    "action_level": "IRRIGATE_NOW|RECHECK_SOON|MONITOR_ONLY",\n'
        '    "action_label": "立即灌溉|先复查后决定|先观察不灌溉",\n'
        '    "decision_score": 0-1,\n'
        '    "decision_score_tip": "分数越高，说明越需要尽快灌溉",\n'
        '    "recheck_after_min": number,\n'
        '    "pulse_plan": [],\n'
        '    "monitoring_plan": {}\n'
        "  },\n"
        '  "decision_reasoning": {\n'
        '    "water_stress_assessment": "...",\n'
        '    "weather_impact_analysis": "...",\n'
        '    "crop_demand_analysis": "...",\n'
        '    "water_saving_strategy": "...",\n'
        '    "plain_language_summary": {"what_happened":"...","what_to_do_now":"...","why":"..."},\n'
        '    "contrast_with_traditional": {"traditional_method":"...","smart_method":"...","estimated_water_saving_pct":0-100,"traditional_reference_amount_mm":number,"smart_recommended_amount_mm":number,"key_differences":["..."]},\n'
        '    "detailed_reasoning": ["..."]\n'
        "  },\n"
        '  "confidence_score": 0-1\n'
        "}\n"
        "要求：语言白话，面向农户。"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _call_llm_for_decision(context: dict) -> tuple[dict | None, str | None]:
    if OpenAI is None:
        return None, "openai_sdk_unavailable"

    api_key = os.getenv("API_KEY")
    model = os.getenv("MODEL")
    base_url = os.getenv("BASE_URL")

    if not api_key or not model:
        return None, "missing_api_env"

    try:
        if base_url:
            client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model=model,
            messages=_build_llm_messages(context),
            temperature=0.2,
            max_tokens=1600,
        )

        content = ""
        if response.choices and response.choices[0].message:
            content = response.choices[0].message.content or ""

        parsed = _extract_json_object(content)
        if not parsed:
            return None, "invalid_json_from_llm"
        return parsed, None
    except Exception as e:  # pragma: no cover - network/model dependent
        logger.warning("LLM decision call failed: %s", e)
        return None, f"llm_call_failed:{str(e)}"


def _normalize_decision_result(raw: dict, context: dict) -> dict:
    decision = raw.get("decision", {}) if isinstance(raw.get("decision"), dict) else {}
    reasoning = (
        raw.get("decision_reasoning", {})
        if isinstance(raw.get("decision_reasoning"), dict)
        else {}
    )

    moisture_gap = context["moisture_gap"]
    current_soil_moisture = context["current_soil_moisture"]
    current_temperature = context["current_temperature"]
    current_humidity = context["current_humidity"]
    crop_ideal_moisture = context["crop_ideal_moisture"]
    rain_forecast_24h = context["rain_forecast_24h"]
    crop_min_temp = context["crop_min_temp"]
    crop_max_temp = context["crop_max_temp"]

    irrigate = bool(decision.get("irrigate", False))
    action_level = str(decision.get("action_level", "")).strip().upper()
    if action_level not in ACTION_LABEL_MAP:
        if irrigate:
            action_level = "IRRIGATE_NOW"
        elif moisture_gap > 0:
            action_level = "RECHECK_SOON"
        else:
            action_level = "MONITOR_ONLY"

    temp_in_range = crop_min_temp <= current_temperature <= crop_max_temp
    severe_dry = (
        moisture_gap >= max(12.0, crop_ideal_moisture * 0.3)
        or current_soil_moisture <= max(15.0, crop_ideal_moisture * 0.35)
    )
    weak_rain = rain_forecast_24h < 1.0
    if severe_dry and temp_in_range and weak_rain:
        action_level = "IRRIGATE_NOW"

    irrigate = action_level == "IRRIGATE_NOW"
    action_label = ACTION_LABEL_MAP[action_level]

    decision_score = _clamp(_to_float(decision.get("decision_score", 0.5), 0.5), 0.0, 1.0)

    irrigation_amount_mm = _clamp(
        _to_float(decision.get("irrigation_amount_mm", 0.0), 0.0), 0.0, 40.0
    )
    if irrigate and irrigation_amount_mm <= 0:
        irrigation_amount_mm = round(max(2.0, moisture_gap * 0.6), 1)
    irrigation_amount_mm = round(irrigation_amount_mm, 1)

    irrigation_duration_min = _to_int(
        decision.get("irrigation_duration_min", 0), 0
    )
    if irrigate and irrigation_duration_min <= 0:
        irrigation_duration_min = max(6, _to_int(irrigation_amount_mm * 2.0, 6))

    irrigation_time_window = str(decision.get("irrigation_time_window", "")).strip()
    if not irrigation_time_window:
        irrigation_time_window = "今天傍晚低蒸发时段" if irrigate else "N/A"

    recheck_after_min = _to_int(
        decision.get("recheck_after_min", 30 if irrigate else 90),
        30 if irrigate else 90,
    )
    recheck_after_min = _to_int(_clamp(float(recheck_after_min), 15.0, 360.0), 90)

    pulse_plan = decision.get("pulse_plan", [])
    if not isinstance(pulse_plan, list):
        pulse_plan = []
    if irrigate and not pulse_plan:
        phase1_amount = round(irrigation_amount_mm * 0.7, 1)
        phase2_amount = round(max(0.0, irrigation_amount_mm - phase1_amount), 1)
        phase1_duration = max(4, _to_int(irrigation_duration_min * 0.7, 4))
        phase2_duration = max(2, max(0, irrigation_duration_min - phase1_duration))
        pulse_plan = [
            {
                "stage": 1,
                "name": "快速补偿灌溉",
                "trigger": "立即执行",
                "amount_mm": phase1_amount,
                "duration_min": phase1_duration,
            },
            {
                "stage": 2,
                "name": "复检微调灌溉",
                "trigger": f"{recheck_after_min}分钟后复检，仍偏干则执行",
                "amount_mm": phase2_amount,
                "duration_min": phase2_duration,
            },
        ]

    monitoring_plan = decision.get("monitoring_plan", {})
    if not isinstance(monitoring_plan, dict):
        monitoring_plan = {}
    if not monitoring_plan:
        monitoring_plan = {
            "next_check_min": recheck_after_min,
            "focus": "跟踪土壤湿度变化趋势",
            "trigger_condition": "若湿度继续下降则转入灌溉",
            "suggested_action": action_label,
        }

    traditional_amount = round(max(8.0, moisture_gap * 1.2), 1)
    smart_reference_amount = (
        irrigation_amount_mm if irrigate else round(max(0.0, moisture_gap * 0.35), 1)
    )
    estimated_saving_pct = round(
        _clamp(
            ((traditional_amount - smart_reference_amount) / traditional_amount * 100.0)
            if traditional_amount > 0
            else 0.0,
            0.0,
            85.0,
        ),
        1,
    )

    contrast = (
        reasoning.get("contrast_with_traditional", {})
        if isinstance(reasoning.get("contrast_with_traditional"), dict)
        else {}
    )
    key_differences = contrast.get("key_differences")
    if not isinstance(key_differences, list) or not key_differences:
        key_differences = [
            "大模型综合判断而非固定阈值触发",
            "同一湿度在不同天气下会给出不同动作",
            "先复查再执行，避免一次性过量灌溉",
        ]

    detailed_reasoning = reasoning.get("detailed_reasoning", [])
    if not isinstance(detailed_reasoning, list) or not detailed_reasoning:
        detailed_reasoning = [
            "系统结合土壤湿度、气温、空气湿度和降雨预报做综合判断。",
            "本次建议不是单一阈值触发，而是按整体风险给出动作级别。",
        ]

    plain_summary = (
        reasoning.get("plain_language_summary", {})
        if isinstance(reasoning.get("plain_language_summary"), dict)
        else {}
    )

    temp_judgement = (
        f"当前气温 {current_temperature}°C 处于作物适温范围（{crop_min_temp}~{crop_max_temp}°C）内。"
        if temp_in_range
        else f"当前气温 {current_temperature}°C 不在作物适温范围（{crop_min_temp}~{crop_max_temp}°C）内。"
    )
    reasoning_water_strategy = str(
        reasoning.get(
            "water_saving_strategy",
            "按综合风险给动作，轻度缺水先复查，避免不必要灌溉。",
        )
    )
    if irrigate and (
        "暂不灌溉" in reasoning_water_strategy
        or "提高后再灌溉" in reasoning_water_strategy
        or "先观察" in reasoning_water_strategy
        or "先复查" in reasoning_water_strategy
    ):
        reasoning_water_strategy = "当前缺水明显，建议先小水补灌并复检，避免持续水分胁迫。"
    if (not irrigate) and ("立即灌溉" in reasoning_water_strategy):
        reasoning_water_strategy = "当前优先继续监测并按复检结果再决策，避免不必要灌溉。"

    final_result = {
        "decision": {
            "irrigate": irrigate,
            "irrigation_amount_mm": irrigation_amount_mm,
            "irrigation_duration_min": irrigation_duration_min,
            "irrigation_time_window": irrigation_time_window,
            "strategy_type": str(decision.get("strategy_type", "LLM_REASONED")),
            "control_mode": str(
                decision.get("control_mode", "大模型综合判断 + 轻量兜底校验")
            ),
            "action_level": action_level,
            "action_label": action_label,
            "decision_score": round(decision_score, 3),
            "decision_score_tip": "分数越高，说明越需要尽快灌溉",
            "target_soil_moisture_pct": round(crop_ideal_moisture, 1),
            "target_moisture_range_pct": {
                "min": round(max(0.0, crop_ideal_moisture - 2.0), 1),
                "ideal": round(crop_ideal_moisture, 1),
                "max": round(min(100.0, crop_ideal_moisture + 1.0), 1),
            },
            "recheck_after_min": recheck_after_min,
            "pulse_plan": pulse_plan,
            "monitoring_plan": monitoring_plan,
        },
        "decision_reasoning": {
            "water_stress_assessment": str(
                reasoning.get(
                    "water_stress_assessment",
                    f"当前土壤湿度与目标差 {moisture_gap:.1f}%，建议：{action_label}。",
                )
            ),
            "weather_impact_analysis": str(
                reasoning.get(
                    "weather_impact_analysis",
                    f"未来24小时预计降雨 {rain_forecast_24h} mm，作为本次判断参考。" if rain_forecast_24h is not None and rain_forecast_24h >= 0 else "天气数据缺失，无法获取降雨预报",
                )
            ),
            "crop_demand_analysis": str(
                (
                    (str(reasoning.get("crop_demand_analysis", "")).strip() + " ")
                    if str(reasoning.get("crop_demand_analysis", "")).strip()
                    else ""
                )
                + (
                    f"作物目标湿度约 {crop_ideal_moisture}%，当前 {current_soil_moisture}%；"
                    f"空气湿度 {current_humidity}% 。{temp_judgement}"
                )
            ),
            "water_saving_strategy": str(
                reasoning_water_strategy
            ),
            "plain_language_summary": {
                "what_happened": str(
                    plain_summary.get("what_happened", f"土壤相对目标偏干 {moisture_gap:.1f}% 。")
                ),
                "what_to_do_now": str(plain_summary.get("what_to_do_now", action_label)),
                "why": str(
                    plain_summary.get(
                        "why",
                        "这次是综合判断，不是“低于某个阈值就必灌”。",
                    )
                ),
            },
            "contrast_with_traditional": {
                "traditional_method": str(
                    contrast.get("traditional_method", "固定时段一次性灌溉，按经验定额")
                ),
                "smart_method": str(
                    contrast.get("smart_method", "大模型综合分析后分级动作，必要时再灌溉")
                ),
                "estimated_water_saving_pct": _clamp(
                    _to_float(contrast.get("estimated_water_saving_pct", estimated_saving_pct), estimated_saving_pct),
                    0.0,
                    100.0,
                ),
                "traditional_reference_amount_mm": _to_float(
                    contrast.get("traditional_reference_amount_mm", traditional_amount),
                    traditional_amount,
                ),
                "smart_recommended_amount_mm": _to_float(
                    contrast.get("smart_recommended_amount_mm", smart_reference_amount),
                    smart_reference_amount,
                ),
                "key_differences": key_differences,
            },
            "detailed_reasoning": detailed_reasoning,
        },
        "confidence_score": round(
            _clamp(_to_float(raw.get("confidence_score", 0.85), 0.85), 0.0, 1.0), 3
        ),
    }

    return final_result


def _fallback_decision(context: dict, reason: str) -> dict:
    moisture_gap = context["moisture_gap"]
    crop_ideal_moisture = context["crop_ideal_moisture"]
    current_temperature = context["current_temperature"]
    current_humidity = context["current_humidity"]
    rain_forecast_24h = context["rain_forecast_24h"]
    crop_min_temp = context["crop_min_temp"]
    crop_max_temp = context["crop_max_temp"]
    crop_optimal_humidity_min = context.get("crop_optimal_humidity_min")
    crop_optimal_humidity_max = context.get("crop_optimal_humidity_max")
    current_soil_ph = context.get("current_soil_ph")
    crop_soil_ph_min = context.get("crop_soil_ph_min")
    crop_soil_ph_max = context.get("crop_soil_ph_max")
    current_light_hours = context.get("current_light_hours")
    crop_daily_light_hours = context.get("crop_daily_light_hours")

    moisture_ratio = moisture_gap / max(crop_ideal_moisture, 1.0)
    if moisture_gap <= 5.0:
        soil_term = 0.0
    else:
        soil_term = max(0.0, moisture_ratio)

    temp_mid = (crop_min_temp + crop_max_temp) / 2.0
    temp_half_span = max((crop_max_temp - crop_min_temp) / 2.0, 1.0)
    temp_term = max(0.0, (current_temperature - temp_mid) / temp_half_span)

    # Air-humidity pressure: prefer crop-specific range; fallback to generic dry-air pressure.
    if crop_optimal_humidity_min is not None and crop_optimal_humidity_max is not None:
        low_humidity_pressure = max(0.0, (crop_optimal_humidity_min - current_humidity) / max(crop_optimal_humidity_min, 1.0))
        high_humidity_relief = max(0.0, (current_humidity - crop_optimal_humidity_max) / max(100.0 - crop_optimal_humidity_max, 1.0))
    else:
        low_humidity_pressure = max(0.0, (50.0 - current_humidity) / 50.0)
        high_humidity_relief = 0.0

    if rain_forecast_24h is None or rain_forecast_24h < 0:
        rain_relief = 0.0
    else:
        rain_relief = min(1.0, max(0.0, rain_forecast_24h / 12.0))

    light_excess_pressure = 0.0
    light_deficit_relief = 0.0
    if crop_daily_light_hours is not None and current_light_hours is not None and crop_daily_light_hours > 0:
        light_excess_pressure = max(0.0, (current_light_hours - crop_daily_light_hours) / crop_daily_light_hours)
        light_deficit_relief = max(0.0, (crop_daily_light_hours - current_light_hours) / crop_daily_light_hours)

    ph_mismatch = 0.0
    if (
        current_soil_ph is not None and
        crop_soil_ph_min is not None and
        crop_soil_ph_max is not None
    ):
        if current_soil_ph < crop_soil_ph_min:
            ph_mismatch = (crop_soil_ph_min - current_soil_ph) / max(crop_soil_ph_min, 0.1)
        elif current_soil_ph > crop_soil_ph_max:
            ph_mismatch = (current_soil_ph - crop_soil_ph_max) / max(crop_soil_ph_max, 0.1)

    decision_score = _clamp(
        0.52 * soil_term +
        0.18 * temp_term +
        0.14 * low_humidity_pressure +
        0.06 * light_excess_pressure +
        0.08 -
        0.30 * rain_relief -
        0.08 * high_humidity_relief -
        0.06 * light_deficit_relief -
        0.05 * min(ph_mismatch, 1.0),
        0.0,
        1.0,
    )

    if decision_score >= 0.65:
        if moisture_gap <= 5.0:
            action_level = "MONITOR_ONLY"
        else:
            action_level = "IRRIGATE_NOW"
    elif decision_score >= 0.40:
        action_level = "RECHECK_SOON"
    else:
        action_level = "MONITOR_ONLY"

    irrigate = action_level == "IRRIGATE_NOW"
    irrigation_amount_mm = round(max(0.0, moisture_gap * 0.6), 1) if irrigate else 0.0
    irrigation_duration_min = max(6, _to_int(irrigation_amount_mm * 2.0, 6)) if irrigate else 0

    raw = {
        "decision": {
            "irrigate": irrigate,
            "irrigation_amount_mm": irrigation_amount_mm,
            "irrigation_duration_min": irrigation_duration_min,
            "irrigation_time_window": "今天傍晚低蒸发时段" if irrigate else "N/A",
            "strategy_type": "LLM_REASONED_FALLBACK",
            "control_mode": "大模型不可用时使用连续评分兜底",
            "action_level": action_level,
            "action_label": ACTION_LABEL_MAP[action_level],
            "decision_score": round(decision_score, 3),
            "target_soil_moisture_pct": round(crop_ideal_moisture, 1),
            "target_moisture_range_pct": {
                "min": round(max(0.0, crop_ideal_moisture - 2.0), 1),
                "ideal": round(crop_ideal_moisture, 1),
                "max": round(min(100.0, crop_ideal_moisture + 1.0), 1),
            },
            "recheck_after_min": 30 if irrigate else 90,
        },
        "decision_reasoning": {
            "water_stress_assessment": (
                f"当前偏干程度约 {moisture_gap:.1f}% ，综合分 {decision_score:.3f}。"
            ),
            "weather_impact_analysis": f"未来24小时降雨 {rain_forecast_24h} mm。",
            "crop_demand_analysis": (
                f"气温 {current_temperature}°C，空气湿度 {current_humidity}%，作物目标湿度 {crop_ideal_moisture}% 。"
            ),
            "water_saving_strategy": "先看综合分再行动，分不高就先观察或复查，避免过灌。",
            "detailed_reasoning": [
                "当前使用的是兜底决策路径。",
                f"触发原因: {reason}",
            ],
        },
        "confidence_score": 0.72,
    }
    return _normalize_decision_result(raw, context)


@mcp.tool()
def make_irrigation_decision(
    current_soil_moisture: float,
    current_temperature: Optional[float],
    current_humidity: float,
    rain_forecast_24h: float,
    crop_ideal_moisture: float,
    crop_min_temp: float,
    crop_max_temp: float,
    crop_optimal_humidity_min: Optional[float] = None,
    crop_optimal_humidity_max: Optional[float] = None,
    crop_soil_ph_min: Optional[float] = None,
    crop_soil_ph_max: Optional[float] = None,
    crop_daily_light_hours: Optional[float] = None,
    current_soil_ph: Optional[float] = None,
    current_light_hours: Optional[float] = None,
) -> str:
    """
    Use LLM-first strategy to make irrigation decisions with lightweight fallback.

    Args:
        current_soil_moisture: Current soil moisture percentage (0-100)
        current_temperature: Current air temperature (Celsius)
        current_humidity: Current air humidity percentage
        rain_forecast_24h: Forecasted rainfall in the next 24 hours (mm)
        crop_ideal_moisture: Ideal soil moisture for the crop (percentage)
        crop_min_temp: Minimum temperature tolerance for the crop
        crop_max_temp: Maximum temperature tolerance for the crop
        crop_optimal_humidity_min: Optional lower bound of ideal air humidity for the crop
        crop_optimal_humidity_max: Optional upper bound of ideal air humidity for the crop
        crop_soil_ph_min: Optional lower bound of ideal soil pH for the crop
        crop_soil_ph_max: Optional upper bound of ideal soil pH for the crop
        crop_daily_light_hours: Optional target daily light hours for the crop
        current_soil_ph: Optional measured current soil pH
        current_light_hours: Optional measured current daily light hours
    """
    if current_temperature is None:
        current_temperature = 25.0

    context = {
        "current_soil_moisture": _clamp(_to_float(current_soil_moisture, 0.0), 0.0, 100.0),
        "current_temperature": _to_float(current_temperature, 25.0),
        "current_humidity": _clamp(_to_float(current_humidity, 0.0), 0.0, 100.0),
        "rain_forecast_24h": max(0.0, _to_float(rain_forecast_24h, 0.0)),
        "crop_ideal_moisture": _clamp(_to_float(crop_ideal_moisture, 50.0), 0.0, 100.0),
        "crop_min_temp": _to_float(crop_min_temp, 5.0),
        "crop_max_temp": _to_float(crop_max_temp, 30.0),
        "crop_optimal_humidity_min": _to_float(crop_optimal_humidity_min, 0.0) if crop_optimal_humidity_min is not None else None,
        "crop_optimal_humidity_max": _to_float(crop_optimal_humidity_max, 0.0) if crop_optimal_humidity_max is not None else None,
        "crop_soil_ph_min": _to_float(crop_soil_ph_min, 0.0) if crop_soil_ph_min is not None else None,
        "crop_soil_ph_max": _to_float(crop_soil_ph_max, 0.0) if crop_soil_ph_max is not None else None,
        "crop_daily_light_hours": _to_float(crop_daily_light_hours, 0.0) if crop_daily_light_hours is not None else None,
        "current_soil_ph": _to_float(current_soil_ph, 0.0) if current_soil_ph is not None else None,
        "current_light_hours": _to_float(current_light_hours, 0.0) if current_light_hours is not None else None,
    }
    context["moisture_gap"] = max(
        0.0, round(context["crop_ideal_moisture"] - context["current_soil_moisture"], 2)
    )

    llm_raw, error = _call_llm_for_decision(context)
    if llm_raw is None:
        result = _fallback_decision(context, error or "unknown_error")
        result["decision_engine"] = {
            "mode": "fallback",
            "reason": error or "llm_unavailable",
        }
        # Add engine prefix to action label (Rule-Fallback)
        if "decision" in result and "action_label" in result["decision"]:
            result["decision"]["action_label"] = f"[Rule] {result['decision']['action_label']}"
    else:
        result = _normalize_decision_result(llm_raw, context)
        result["decision_engine"] = {
            "mode": "llm_primary",
            "reason": "llm_success",
        }
        # Add engine prefix to action label (LLM-Primary)
        if "decision" in result and "action_label" in result["decision"]:
            result["decision"]["action_label"] = f"[LLM] {result['decision']['action_label']}"

    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
