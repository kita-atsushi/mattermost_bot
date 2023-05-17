from mattermostdriver import Driver
from typing import Optional
import json
import asyncio
import re
import os
import aiohttp
from v3 import Chatbot
from log import getlogger

logger = getlogger()


class Bot:
    def __init__(
        self,
        server_url: str,
        username: str,
        access_token: Optional[str] = None,
        login_id: Optional[str] = None,
        password: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        openai_api_endpoint: Optional[str] = None,
        port: int = 443,
        timeout: int = 30,
    ) -> None:
        if server_url is None:
            raise ValueError("server url must be provided")

        if port is None:
            self.port = 443

        if timeout is None:
            self.timeout = 30

        # login relative info
        if access_token is None and password is None:
            raise ValueError("Either token or password must be provided")

        if access_token is not None:
            self.driver = Driver(
                {
                    "token": access_token,
                    "url": server_url,
                    "port": self.port,
                    "request_timeout": self.timeout,
                }
            )
        else:
            self.driver = Driver(
                {
                    "login_id": login_id,
                    "password": password,
                    "url": server_url,
                    "port": self.port,
                    "request_timeout": self.timeout,
                }
            )

        # @chatgpt
        if username is None:
            raise ValueError("username must be provided")
        else:
            self.username = username

        # openai_api_endpoint
        if openai_api_endpoint is None:
            self.openai_api_endpoint = "https://api.openai.com/v1/chat/completions"
        else:
            self.openai_api_endpoint = openai_api_endpoint

        # aiohttp session
        self.session = aiohttp.ClientSession()

        self.openai_api_key = openai_api_key
        # initialize chatGPT class
        if self.openai_api_key is not None:
            self.headers = {
                "Content-Type": "application/json",
                "api-key": f"{self.openai_api_key}",
            }

            self.chatbot = Chatbot(
                api_key=self.openai_api_key,
                openai_api_endpoint=self.openai_api_endpoint
            ).chatbot
        else:
            logger.warning("openai_api_key is not provided")

    # close session
    def __del__(self) -> None:
        self.driver.disconnect()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()

    def login(self) -> None:
        self.driver.login()

    async def run(self) -> None:
        await self.driver.init_websocket(self.websocket_handler)

    # websocket handler
    async def websocket_handler(self, message) -> None:
        print(message)
        response = json.loads(message)
        if "event" in response:
            event_type = response["event"]
            if event_type == "posted":
                raw_data = response["data"]["post"]
                raw_data_dict = json.loads(raw_data)
                user_id = raw_data_dict["user_id"]
                post_id = raw_data_dict["id"]
                channel_id = raw_data_dict["channel_id"]
                channel_display_name = response["data"]["channel_display_name"]
                sender_name = response["data"]["sender_name"]
                raw_message = raw_data_dict["message"]

                post_id = raw_data_dict["id"]
                root_id = raw_data_dict["root_id"]

                if not raw_message.startswith(self.username):
                    return

                send_message = ""
                if root_id == '':
                    # First post
                    root_id = post_id
                    send_message = raw_message
                else:
                    if not self.chatbot.exists_convo_id(root_id):
                        send_message = self._add_past_messages(raw_message, post_id)
                    else:
                        send_message = raw_message
                try:
                    prop = {
                        'event_type': event_type, 'sender_name': sender_name, 'message': send_message,
                        'channel_display_name': channel_display_name, 'root_id': root_id, 'post_id': post_id
                    }
                    logger.info(json.dumps(prop, ensure_ascii=False), extra={'custom_dimensions': prop})
                    asyncio.create_task(
                        self.message_callback(
                            send_message, channel_id, user_id, sender_name, root_id
                        )
                    )
                except Exception as e:
                    await asyncio.to_thread(self.send_message, channel_id, root_id, f"{e}")

    # message callback
    async def message_callback(
        self, raw_message: str, channel_id: str, user_id: str, sender_name: str, root_id: str
    ) -> None:
        # prevent command trigger loop
        if sender_name != self.username:
            prompt = raw_message.lstrip(self.username)
            try:
                logger.info("Starting chat", extra={'custom_dimensions': {'root_id': root_id, 'sender_name': sender_name}})
                response = await self.chat(prompt, root_id)
                await asyncio.to_thread(
                    self.send_message, channel_id, root_id, f"{response}"
                )
            except Exception as e:
                logger.error(e, exc_info=True)
                raise Exception(e)

    def _add_past_messages(self, message: str, post_id: str) -> str:
        messages = [message]
        past_conversations = self._get_thread_posts(post_id)
        max_past = 2
        for order in past_conversations['order'][1:max_past]:
            raw_post = past_conversations['posts'][order]['message']
            messages.append(raw_post)
        return "\n".join(messages)

    def _get_thread_posts(self, post_id: str) -> dict:
        resp_posts = self.driver.posts.get_thread(post_id)
        # NOTE: sort desc order by posts.create_at
        sorted_posts = sorted(resp_posts['posts'].values(), key=lambda x: x['create_at'], reverse=True)
        resp_posts['posts'] = {post['id']: post for post in sorted_posts}
        resp_posts['order'] = [post['id'] for post in sorted_posts]
        return resp_posts

    # send message to room
    def send_message(self, channel_id: str, root_id: str, message: str) -> None:
        self.driver.posts.create_post(
            options={
                "channel_id": channel_id,
                "root_id": root_id,
                "message": message,
            }
        )

    # send file to room
    def send_file(self, channel_id: str, message: str, filepath: str) -> None:
        filename = os.path.split(filepath)[-1]
        try:
            file_id = self.driver.files.upload_file(
                channel_id=channel_id,
                files={
                    "files": (filename, open(filepath, "rb")),
                },
            )["file_infos"][0]["id"]
        except Exception as e:
            logger.error(e, exc_info=True)
            raise Exception(e)

        try:
            self.driver.posts.create_post(
                options={
                    "channel_id": channel_id,
                    "message": message,
                    "file_ids": [file_id],
                }
            )
            # remove image after posting
            os.remove(filepath)
        except Exception as e:
            logger.error(e, exc_info=True)
            raise Exception(e)

    async def chat(self, prompt: str, root_id: str) -> str:
        return await self.chatbot.ask_async(prompt, convo_id=root_id)
