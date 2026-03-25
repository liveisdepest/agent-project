from mcp.server.fastmcp import FastMCP
import json

mcp = FastMCP("crop_knowledge")

# Simple in-memory knowledge base
CROP_DATA = {
    "tomato": {
        "name": "Tomato",
        "growth_stages": ["Seedling", "Vegetative", "Flowering", "Fruit Formation", "Ripening"],
        "water_needs": {
            "Seedling": "Low",
            "Vegetative": "Medium",
            "Flowering": "High",
            "Fruit Formation": "High",
            "Ripening": "Medium"
        },
        "ideal_soil_moisture": 60.0,  # percentage
        "min_temperature": 10.0,
        "max_temperature": 35.0,
        "optimal_air_humidity_min": 55.0,
        "optimal_air_humidity_max": 75.0,
        "soil_ph_min": 6.0,
        "soil_ph_max": 6.8,
        "daily_light_hours": 7.0
    },
    "corn": {
        "name": "Corn",
        "growth_stages": ["Germination", "Vegetative", "Tasseling", "Silking", "Grain Fill", "Maturity"],
        "water_needs": {
            "Germination": "Medium",
            "Vegetative": "High",
            "Tasseling": "Very High",
            "Silking": "Very High",
            "Grain Fill": "High",
            "Maturity": "Low"
        },
        "ideal_soil_moisture": 70.0,
        "min_temperature": 15.0,
        "max_temperature": 35.0,
        "optimal_air_humidity_min": 50.0,
        "optimal_air_humidity_max": 70.0,
        "soil_ph_min": 5.8,
        "soil_ph_max": 7.0,
        "daily_light_hours": 8.0
    },
    "wheat": {
        "name": "Wheat",
        "growth_stages": ["Seedling", "Tillering", "Stem Extension", "Heading", "Ripening"],
        "water_needs": {
            "Seedling": "Low",
            "Tillering": "Medium",
            "Stem Extension": "High",
            "Heading": "High",
            "Ripening": "Low"
        },
        "ideal_soil_moisture": 50.0,
        "min_temperature": 5.0,
        "max_temperature": 30.0,
        "optimal_air_humidity_min": 45.0,
        "optimal_air_humidity_max": 65.0,
        "soil_ph_min": 6.0,
        "soil_ph_max": 7.0,
        "daily_light_hours": 6.0
    },
    "pineapple": {
        "name": "Pineapple",
        "growth_stages": ["Seedling", "Vegetative", "Flower Induction", "Fruit Development", "Maturity"],
        "water_needs": {
            "Seedling": "Medium",
            "Vegetative": "Medium",
            "Flower Induction": "Medium",
            "Fruit Development": "High",
            "Maturity": "Medium"
        },
        "ideal_soil_moisture": 65.0,
        "min_temperature": 18.0,
        "max_temperature": 30.0,
        "optimal_air_humidity_min": 60.0,
        "optimal_air_humidity_max": 80.0,
        "soil_ph_min": 4.5,
        "soil_ph_max": 5.5,
        "daily_light_hours": 6.0
    }
}

CROP_ALIASES = {
    "\u756a\u8304": "tomato",
    "\u897f\u7ea2\u67ff": "tomato",
    "\u7389\u7c73": "corn",
    "\u5c0f\u9ea6": "wheat",
    "\u83e0\u841d": "pineapple",
    "\u51e4\u68a8": "pineapple",
}

@mcp.tool()
def get_crop_info(crop_name: str) -> str:
    """
    Get agronomic knowledge for a specific crop.

    Args:
        crop_name: Name of the crop (e.g., "tomato", "corn", "wheat", "pineapple")
    """
    crop_key = crop_name.lower().strip()
    crop_key = CROP_ALIASES.get(crop_key, crop_key)

    if crop_key in CROP_DATA:
        return json.dumps(CROP_DATA[crop_key], indent=2, ensure_ascii=False)
    else:
        return f"Crop '{crop_name}' not found in knowledge base. Available crops: {list(CROP_DATA.keys())}"


@mcp.tool()
def get_water_requirements(crop_name: str, growth_stage: str) -> str:
    """
    Get water requirements for a crop at a specific growth stage.

    Args:
        crop_name: Name of the crop
        growth_stage: Current growth stage
    """
    crop_key = crop_name.lower().strip()
    crop_key = CROP_ALIASES.get(crop_key, crop_key)

    if crop_key not in CROP_DATA:
        return f"Crop '{crop_name}' not found."

    crop = CROP_DATA[crop_key]
    stage_needs = crop["water_needs"]

    if growth_stage in stage_needs:
        return f"Water needs for {crop['name']} at {growth_stage}: {stage_needs[growth_stage]}"

    for stage, needs in stage_needs.items():
        if growth_stage.lower() in stage.lower():
            return f"Water needs for {crop['name']} at {stage}: {needs}"

    return f"Growth stage '{growth_stage}' not found for {crop['name']}. Available stages: {crop['growth_stages']}"


if __name__ == "__main__":
    mcp.run(transport='stdio')

