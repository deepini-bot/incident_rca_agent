from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import text

from common.observability import setup_service
from common.http import make_client, call_json
from common.db import make_engine, connection

app = FastAPI(title="orders")
setup_service(app)
engine = make_engine()
client = make_client()


class OrderIn(BaseModel):
    user_id: int
    product_id: int
    qty: int = 1


def insert_order(req: OrderIn) -> int:
    with connection(engine) as c:
        res = c.execute(
            text("INSERT INTO orders (user_id, product_id, qty, status) VALUES (:u, :p, :q, 'pending')"),
            {"u": req.user_id, "p": req.product_id, "q": req.qty},
        )
        return res.lastrowid


def set_status(order_id: int, status: str, amount: float) -> None:
    with connection(engine) as c:
        c.execute(text("UPDATE orders SET status=:s, amount=:a WHERE id=:id"),
                  {"s": status, "a": amount, "id": order_id})


def fetch_order(order_id: int):
    with connection(engine) as c:
        row = c.execute(text("SELECT id, user_id, product_id, qty, amount, status FROM orders WHERE id=:id"),
                        {"id": order_id}).mappings().first()
        return dict(row) if row else None


@app.post("/orders")
async def create_order(req: OrderIn):
    order_id = await run_in_threadpool(insert_order, req)
    try:
        inv = await call_json(client, "inventory", "POST", "/reserve",
                              json={"product_id": req.product_id, "qty": req.qty})
        amount = round(inv["price"] * req.qty, 2)
        pay = await call_json(client, "payments", "POST", "/charge",
                              json={"order_id": order_id, "amount": amount})
    except HTTPException:
        await run_in_threadpool(set_status, order_id, "failed", 0)
        raise
    await run_in_threadpool(set_status, order_id, "paid", amount)
    return {"order_id": order_id, "amount": amount, "payment_id": pay["payment_id"], "status": "paid"}


@app.get("/orders/{order_id}")
async def get_order(order_id: int):
    row = await run_in_threadpool(fetch_order, order_id)
    if not row:
        raise HTTPException(404, "order not found")
    return row
