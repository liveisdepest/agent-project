from server.irrigation.actuators.pump import set_pump_state
from server.irrigation.actuators.valve import set_valve_state
import asyncio
import logging

logger = logging.getLogger(__name__)
_zone_stop_tasks: dict[str, asyncio.Task] = {}


def cancel_all_failsafe_tasks() -> None:
    for zone, task in list(_zone_stop_tasks.items()):
        if not task.done():
            task.cancel()
        _zone_stop_tasks.pop(zone, None)


def _schedule_failsafe_stop(zone: str, duration_minutes: int) -> None:
    async def _auto_stop_task() -> None:
        try:
            await asyncio.sleep(duration_minutes * 60)
            await set_pump_state(False)
            await set_valve_state(zone, False)
            logger.info(
                "Failsafe auto-stop executed for zone %s after %s minutes",
                zone,
                duration_minutes,
            )
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("Failsafe auto-stop failed for zone %s: %s", zone, e)
        finally:
            _zone_stop_tasks.pop(zone, None)

    old_task = _zone_stop_tasks.get(zone)
    if old_task and not old_task.done():
        old_task.cancel()
    _zone_stop_tasks[zone] = asyncio.create_task(_auto_stop_task())

async def start_irrigation(zone: str, duration_minutes: int) -> str:
    """
    Starts irrigation for a specific zone for a given duration.
    """
    try:
        if duration_minutes <= 0:
            return "Failed to start irrigation: duration_minutes must be greater than 0"
        # Open valve first
        await set_valve_state(zone, True)
        # Then start pump
        await set_pump_state(True)
        _schedule_failsafe_stop(zone, duration_minutes)
        
        msg = f"Irrigation started for zone {zone} for {duration_minutes} minutes."
        logger.info(msg)
        
        
        return msg
    except Exception as e:
        return f"Failed to start irrigation: {str(e)}"
