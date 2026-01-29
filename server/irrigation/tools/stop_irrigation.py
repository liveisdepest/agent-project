from server.irrigation.actuators.pump import set_pump_state
from server.irrigation.actuators.valve import set_valve_state
import logging

logger = logging.getLogger(__name__)

async def stop_irrigation() -> str:
    """
    Stops all irrigation (turns off pump and closes valves).
    """
    try:
        # Stop pump first
        await set_pump_state(False)
        # Then close valve (assuming we close all or specific one, for now log)
        # In a real system we might track active zones. 
        # Here we just log a generic close.
        await set_valve_state("ALL", False)
        
        msg = "Irrigation stopped."
        logger.info(msg)
        return msg
    except Exception as e:
        return f"Failed to stop irrigation: {str(e)}"
