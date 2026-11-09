from fastapi import FastAPI, HTTPException
import httpx

app = FastAPI(title="Storefront API Gateway", version="1.0.0")

ORDER_SERVICE_URL = "http://order-service:8001"
PAYMENT_SERVICE_URL = "http://payment-service:8002"


@app.get("/api/v1/health")
async def gateway_health():
    return {"status": "healthy", "service": "api-gateway"}


@app.get("/api/v1/catalog/products")
async def list_products():
    return {
        "products": [
            {"id": "sku-101", "name": "Enterprise Server Blade", "price_usd": 2499.00},
            {"id": "sku-102", "name": "Redundant Power Supply", "price_usd": 399.00},
        ]
    }


@app.post("/api/v1/checkout/orders")
async def create_checkout_order(payload: dict):
    async with httpx.AsyncClient() as client:
        # Calls downstream order-service and payment-service
        order_resp = await client.post(f"{ORDER_SERVICE_URL}/orders", json=payload)
        if order_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail="Order service failure")
        payment_resp = await client.post(f"{PAYMENT_SERVICE_URL}/charge", json=payload)
        return {
            "order": order_resp.json(),
            "payment": payment_resp.json(),
        }

