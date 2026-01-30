from mcp.server.fastmcp import FastMCP
import json

mcp = FastMCP("decision")

@mcp.tool()
def make_irrigation_decision(
    current_soil_moisture: float,
    current_temperature: float,
    current_humidity: float,
    rain_forecast_24h: float,
    crop_ideal_moisture: float,
    crop_min_temp: float,
    crop_max_temp: float
) -> str:
    """
    Make an irrigation decision based on environmental data and crop requirements.
    
    Args:
        current_soil_moisture: Current soil moisture percentage (0-100)
        current_temperature: Current air temperature (Celsius)
        current_humidity: Current air humidity percentage
        rain_forecast_24h: Forecasted rainfall in the next 24 hours (mm)
        crop_ideal_moisture: Ideal soil moisture for the crop (percentage)
        crop_min_temp: Minimum temperature tolerance for the crop
        crop_max_temp: Maximum temperature tolerance for the crop
    """
    
    reasons = []
    should_irrigate = False
    irrigation_amount = 0
    irrigation_duration = 0
    
    # Logic 1: Soil Moisture Check
    moisture_gap = crop_ideal_moisture - current_soil_moisture
    if moisture_gap > 0:
        reasons.append(f"Soil moisture ({current_soil_moisture}%) is below target ({crop_ideal_moisture}%). Gap: {moisture_gap}%")
        
        # Logic 2: Rain Forecast Check
        if rain_forecast_24h > 5.0: # If more than 5mm rain expected
            reasons.append(f"Rain forecast ({rain_forecast_24h}mm) is sufficient. Skipping irrigation.")
            should_irrigate = False
        else:
            should_irrigate = True
            # Simple calculation: 1% gap ~= 1 minute of irrigation (just a heuristic)
            irrigation_duration = max(5, int(moisture_gap * 1.5)) 
            irrigation_amount = moisture_gap * 0.5 # mm
            reasons.append(f"Rain forecast ({rain_forecast_24h}mm) is insufficient.")
    else:
        reasons.append(f"Soil moisture ({current_soil_moisture}%) is adequate (Target: {crop_ideal_moisture}%).")
        should_irrigate = False

    # Logic 3: Temperature Constraints
    if current_temperature < crop_min_temp:
        if should_irrigate:
             reasons.append(f"WARNING: Temperature ({current_temperature}°C) is too low. Irrigation might cause freezing/stress.")
             # Maybe reduce or cancel? Let's keep it but warn.
    elif current_temperature > crop_max_temp:
        if should_irrigate:
             reasons.append(f"Temperature ({current_temperature}°C) is high. Ensuring sufficient water to cool crop.")
             irrigation_duration += 10 # Add extra time

    result = {
        "decision": {
            "irrigate": should_irrigate,
            "irrigation_amount_mm": irrigation_amount,
            "irrigation_duration_min": irrigation_duration,
            "irrigation_time_window": "Immediate" if should_irrigate else "N/A"
        },
        "decision_reasoning": {
            "water_stress_assessment": f"Moisture gap is {moisture_gap:.1f}%",
            "weather_impact_analysis": f"Rain forecast: {rain_forecast_24h}mm",
            "crop_demand_analysis": f"Ideal: {crop_ideal_moisture}%, Current: {current_soil_moisture}%",
            "water_saving_strategy": "Checked forecast to avoid waste.",
            "detailed_reasoning": reasons
        },
        "confidence_score": 0.95
    }
    
    return json.dumps(result, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    mcp.run(transport='stdio')
