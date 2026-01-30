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
        "ideal_soil_moisture": 60.0, # percentage
        "min_temperature": 10.0,
        "max_temperature": 35.0
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
        "max_temperature": 35.0
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
        "max_temperature": 30.0
    }
}

@mcp.tool()
def get_crop_info(crop_name: str) -> str:
    """
    Get agronomic knowledge for a specific crop.
    
    Args:
        crop_name: Name of the crop (e.g., "tomato", "corn", "wheat")
    """
    crop_key = crop_name.lower()
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
    crop_key = crop_name.lower()
    if crop_key not in CROP_DATA:
        return f"Crop '{crop_name}' not found."
    
    crop = CROP_DATA[crop_key]
    # Simple fuzzy match for stage
    stage_needs = crop["water_needs"]
    
    # Try exact match
    if growth_stage in stage_needs:
         return f"Water needs for {crop['name']} at {growth_stage}: {stage_needs[growth_stage]}"
    
    # Try partial match
    for stage, needs in stage_needs.items():
        if growth_stage.lower() in stage.lower():
             return f"Water needs for {crop['name']} at {stage}: {needs}"
             
    return f"Growth stage '{growth_stage}' not found for {crop['name']}. Available stages: {crop['growth_stages']}"

if __name__ == "__main__":
    mcp.run(transport='stdio')
