import asyncio
from weather import get_observe

async def test():
    result = await get_observe("kunming")
    print("天气API返回结果:")
    print(result)

if __name__ == "__main__":
    asyncio.run(test())