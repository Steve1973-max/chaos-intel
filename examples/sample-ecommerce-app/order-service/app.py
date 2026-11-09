import os
from fastapi import FastAPI
from sqlalchemy import create_engine, text
import redis
import requests

app = FastAPI(title="Order Processing Service", version="1.0.0")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@orders-db:5432/orders")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis-cache:6379/0")

engine = create_engine(DATABASE_URL)
cache = redis.from_url(REDIS_URL)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "order-service"}


@app.post("/orders")
def create_order(order_payload: dict):
    # Risk: synchronous external call without timeout inside database transaction
    inventory_check = requests.get("http://inventory-service:8003/stock/verify")
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO orders (customer_id, status) VALUES (:cid, 'CREATED')"), {
            "cid": order_payload.get("customer_id", "cust-01")
        })
    cache.set(f"order:latest", "created")
    return {"order_id": "ord-9001", "status": "CREATED", "inventory": inventory_check.status_code}


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    return {"order_id": order_id, "status": "CREATED"}

