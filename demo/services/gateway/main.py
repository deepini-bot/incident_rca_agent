from fastapi import FastAPI
from pydantic import BaseModel

from common.observability import setup_service
from common.http import make_client, call_json

app = FastAPI(title="gateway")
setup_service(app)
client = make_client()


class Checkout(BaseModel):
    user_id: int
    product_id: int
    qty: int = 1


@app.post("/checkout")
async def checkout(req: Checkout):
    return await call_json(client, "orders", "POST", "/orders", json=req.model_dump())


@app.get("/products")
async def products():
    return await call_json(client, "inventory", "GET", "/products")
