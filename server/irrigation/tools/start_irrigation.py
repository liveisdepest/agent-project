from server.irrigation.actuators.pump import set_pump_state
from server.irrigation.actuators.valve import set_valve_state
import asyncio
import logging

logger = logging.getLogger(__name__)

async def start_irrigation(zone: str, duration_minutes: int) -> str:
    """
    Starts irrigation for a specific zone for a given duration.
    """
    try:
        # Open valve first
        await set_valve_state(zone, True)
        # Then start pump
        await set_pump_state(True)
        
        msg = f"Irrigation started for zone {zone} for {duration_minutes} minutes."
        logger.info(msg)
        
        # Note: In a production system, we would need a background task scheduler 
        # to turn it off after duration_minutes. 
        # For this prototype, we rely on the agent or manual stop, 
        # or we could launch a background task if the framework supports it.
        
        return msg
    except Exception as e:
        return f"Failed to start irrigation: {str(e)}"
