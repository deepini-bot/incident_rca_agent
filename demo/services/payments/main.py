import asyncio
import logging
import random

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import text

from common.observability import setup_service
from common.db import make_engine, connection

app = FastAPI(title="payments")
setup_service(app)
engine = make_engine()
log = logging.getLogger("app")


class ChargeIn(BaseModel):
    order_id: int
    amount: float


def insert_payment(req: ChargeIn) -> int:
    with connection(engine) as c:
        res = c.execute(
            text("INSERT INTO payments (order_ref, amount, status) VALUES (:o, :a, 'captured')"),
            {"o": req.order_id, "a": req.amount},
        )
        return res.lastrowid


@app.post("/charge")
async def charge(req: ChargeIn):
    await asyncio.sleep(random.uniform(0.01, 0.03))  # simulated card-processor call
    if random.random() < 0.01:                        # natural background noise
        log.warning(f"card declined for order {req.order_id}")
        raise HTTPException(402, "card declined")
    payment_id = await run_in_threadpool(insert_payment, req)
    return {"payment_id": payment_id, "status": "captured"}
