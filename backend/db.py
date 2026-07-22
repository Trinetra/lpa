"""Shared MongoDB client.

The Motor client is constructed lazily on first access so that the ``services``
modules can be imported in isolation (e.g. by tests) without requiring
MONGO_URL/DB_NAME to be set. Under supervisor, server.py loads ``.env`` at
process start so the first ``db`` access reads the correct values.
"""

import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[os.environ["DB_NAME"]]


class _LazyDB:
    """Attribute-forwarding proxy so ``from db import db; db.users`` still works
    while deferring the actual client construction until first use."""

    def __getattr__(self, name):
        return getattr(get_db(), name)

    def __getitem__(self, name):
        """Supports db["collection_name"] for dynamic/programmatic access
        (e.g. iterating a list of collection names), same as db.collection_name."""
        return get_db()[name]


db = _LazyDB()


# Keep `client` importable for teardown code that may call ``client.close()``.
class _LazyClient:
    def __getattr__(self, name):
        return getattr(get_client(), name)


client = _LazyClient()
