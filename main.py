from bot import Bot
import json
import os
import asyncio


async def main():
    mattermost_bot = Bot(
        server_url=os.environ.get("SERVER_URL"),
        access_token=os.environ.get("ACCESS_TOKEN"),
        login_id=os.environ.get("LOGIN_ID"),
        password=os.environ.get("PASSWORD"),
        username=os.environ.get("USERNAME"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        openai_api_endpoint=os.environ.get("OPENAI_API_ENDPOINT"),
        port=os.environ.get("PORT"),
        timeout=os.environ.get("TIMEOUT"),
    )

    mattermost_bot.login()

    await mattermost_bot.run()


if __name__ == "__main__":
    asyncio.run(main())
