from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import text

from common.observability import setup_service
from common.db import make_engine, connection

app = FastAPI(title="inventory")
setup_service(app)
engine = make_engine()


class ReserveIn(BaseModel):
    product_id: int
    qty: int = Field(1, ge=1)


def list_products():
    with connection(engine) as c:
        return [dict(r) for r in c.execute(text("SELECT id, name, price, stock FROM products LIMIT 20")).mappings()]


def reserve(req: ReserveIn):
    with connection(engine) as c:
        row = c.execute(text("SELECT price FROM products WHERE id=:id"), {"id": req.product_id}).first()
        if row is None:
            return "missing", None
        res = c.execute(text("UPDATE products SET stock = stock - :q WHERE id=:id AND stock >= :q"),
                        {"q": req.qty, "id": req.product_id})
        if res.rowcount == 0:
            return "out_of_stock", None
        return "ok", float(row[0])


@app.get("/products")
async def products():
    return await run_in_threadpool(list_products)


@app.post("/reserve")
async def reserve_stock(req: ReserveIn):
    result, price = await run_in_threadpool(reserve, req)
    if result == "missing":
        raise HTTPException(404, "product not found")
    if result == "out_of_stock":
        raise HTTPException(409, "out of stock")
    return {"product_id": req.product_id, "reserved": req.qty, "price": price}
