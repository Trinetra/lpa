"""Shared MongoDB client used by server.py and services/*.

Reads MONGO_URL and DB_NAME from environment (dotenv already loaded by
server.py at process startup)."""

import os

from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]
