import random

from locust import HttpUser, task, between


class Shopper(HttpUser):
    wait_time = between(0.5, 1.5)

    @task(8)
    def checkout(self):
        self.client.post(
            "/checkout",
            json={"user_id": random.randint(1, 500),
                  "product_id": random.randint(1, 20),
                  "qty": random.randint(1, 3)},
            name="/checkout",
        )

    @task(2)
    def browse(self):
        self.client.get("/products", name="/products")
