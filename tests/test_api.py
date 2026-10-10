import asyncio
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.database import get_db
from app.main import app


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path):
    db_file = tmp_path / "test.db"

    # tables come from the Alembic migrations, the app itself uses the async engine
    command.upgrade(alembic_config_for(db_file), "head")

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    TestingSession = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def create_machine(client, name="Lobby", location="Floor 1"):
    response = client.post("/machines", json={"name": name, "location": location})
    return response.json()["id"]


def create_product(client, name="Cola", price=1.5):
    response = client.post("/products", json={"name": name, "price": price})
    return response.json()["id"]


def test_create_and_get_machine(client):
    response = client.post("/machines", json={"name": "Lobby", "location": "Floor 1"})
    assert response.status_code == 201
    machine_id = response.json()["id"]

    response = client.get(f"/machines/{machine_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Lobby"
    assert len(client.get("/machines").json()) == 1


def test_create_product(client):
    response = client.post("/products", json={"name": "Cola", "price": 1.5})
    assert response.status_code == 201
    assert response.json()["price"] == 1.5
    assert len(client.get("/products").json()) == 1


def test_product_price_must_be_positive(client):
    response = client.post("/products", json={"name": "Free", "price": 0})
    assert response.status_code == 422


def test_add_inventory(client):
    machine_id = create_machine(client)
    product_id = create_product(client)

    response = client.post(
        f"/machines/{machine_id}/inventory",
        json={"product_id": product_id, "quantity": 10},
    )
    assert response.status_code == 201

    items = client.get(f"/machines/{machine_id}/inventory").json()
    assert len(items) == 1
    assert items[0]["quantity"] == 10
    assert items[0]["product"]["name"] == "Cola"


def test_duplicate_product_in_machine_is_rejected(client):
    machine_id = create_machine(client)
    product_id = create_product(client)
    body = {"product_id": product_id, "quantity": 3}

    client.post(f"/machines/{machine_id}/inventory", json=body)
    response = client.post(f"/machines/{machine_id}/inventory", json=body)
    assert response.status_code == 409


def test_update_quantity(client):
    machine_id = create_machine(client)
    product_id = create_product(client)
    client.post(
        f"/machines/{machine_id}/inventory",
        json={"product_id": product_id, "quantity": 10},
    )

    response = client.put(
        f"/machines/{machine_id}/inventory/{product_id}", json={"quantity": 7}
    )
    assert response.status_code == 200
    assert response.json()["quantity"] == 7


def test_negative_quantity_is_rejected(client):
    machine_id = create_machine(client)
    product_id = create_product(client)

    response = client.post(
        f"/machines/{machine_id}/inventory",
        json={"product_id": product_id, "quantity": -1},
    )
    assert response.status_code == 422


def test_low_stock_with_machine_filter(client):
    machine_a = create_machine(client, "A")
    machine_b = create_machine(client, "B")
    cola = create_product(client, "Cola")
    chips = create_product(client, "Chips")

    client.post(f"/machines/{machine_a}/inventory", json={"product_id": cola, "quantity": 2})
    client.post(f"/machines/{machine_a}/inventory", json={"product_id": chips, "quantity": 20})
    client.post(f"/machines/{machine_b}/inventory", json={"product_id": cola, "quantity": 4})

    all_low = client.get("/low-stock").json()
    assert len(all_low) == 2

    only_a = client.get("/low-stock", params={"machine_id": machine_a}).json()
    assert len(only_a) == 1
    assert only_a[0]["product"]["name"] == "Cola"


def test_missing_records_return_404(client):
    machine_id = create_machine(client)

    assert client.get("/machines/999").status_code == 404
    assert client.get("/machines/999/inventory").status_code == 404

    response = client.post(
        f"/machines/{machine_id}/inventory", json={"product_id": 999, "quantity": 1}
    )
    assert response.status_code == 404

    response = client.put(f"/machines/{machine_id}/inventory/999", json={"quantity": 1})
    assert response.status_code == 404


def test_low_stock_limit_is_below_five(client):
    machine_id = create_machine(client)
    empty = create_product(client, "Empty")
    four = create_product(client, "Four")
    five = create_product(client, "Five")

    for product_id, quantity in [(empty, 0), (four, 4), (five, 5)]:
        client.post(
            f"/machines/{machine_id}/inventory",
            json={"product_id": product_id, "quantity": quantity},
        )

    quantities = [item["quantity"] for item in client.get("/low-stock").json()]
    assert sorted(quantities) == [0, 4]


def test_update_with_negative_quantity_is_rejected(client):
    machine_id = create_machine(client)
    product_id = create_product(client)
    client.post(
        f"/machines/{machine_id}/inventory",
        json={"product_id": product_id, "quantity": 10},
    )

    response = client.put(
        f"/machines/{machine_id}/inventory/{product_id}", json={"quantity": -5}
    )
    assert response.status_code == 422


def test_add_inventory_to_missing_machine_returns_404(client):
    product_id = create_product(client)

    response = client.post(
        "/machines/999/inventory", json={"product_id": product_id, "quantity": 1}
    )
    assert response.status_code == 404


def test_delete_inventory_item(client):
    machine_id = create_machine(client)
    product_id = create_product(client)
    client.post(
        f"/machines/{machine_id}/inventory",
        json={"product_id": product_id, "quantity": 10},
    )

    response = client.delete(f"/machines/{machine_id}/inventory/{product_id}")
    assert response.status_code == 204

    assert client.get(f"/machines/{machine_id}/inventory").json() == []


def test_delete_inventory_keeps_the_product(client):
    machine_id = create_machine(client)
    product_id = create_product(client)
    client.post(
        f"/machines/{machine_id}/inventory",
        json={"product_id": product_id, "quantity": 10},
    )

    client.delete(f"/machines/{machine_id}/inventory/{product_id}")

    products = client.get("/products").json()
    assert [product["id"] for product in products] == [product_id]


def test_delete_inventory_from_missing_machine_returns_404(client):
    response = client.delete("/machines/999/inventory/1")
    assert response.status_code == 404


def test_delete_missing_inventory_item_returns_404(client):
    machine_id = create_machine(client)
    product_id = create_product(client)

    response = client.delete(f"/machines/{machine_id}/inventory/{product_id}")
    assert response.status_code == 404


def test_data_is_stored_in_the_test_database(client, tmp_path):
    create_machine(client)

    with sqlite3.connect(tmp_path / "test.db") as connection:
        count = connection.execute("SELECT COUNT(*) FROM machines").fetchone()[0]
    assert count == 1


def test_session_is_closed_after_request(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}")
    monkeypatch.setattr(database, "SessionLocal", async_sessionmaker(engine))

    async def use_session():
        sessions = get_db()
        db = await anext(sessions)
        await db.execute(text("SELECT 1"))
        was_open = db.in_transaction()
        await sessions.aclose()
        return was_open, db.in_transaction()

    was_open, still_open = asyncio.run(use_session())
    assert was_open is True
    assert still_open is False


def alembic_config_for(db_file):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")
    return config


def table_names(db_file):
    with sqlite3.connect(db_file) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {name for (name,) in rows}


def test_migration_creates_tables(tmp_path):
    db_file = tmp_path / "migrated.db"

    command.upgrade(alembic_config_for(db_file), "head")

    assert {"machines", "products", "inventory"} <= table_names(db_file)


def test_migration_can_be_downgraded_and_reapplied(tmp_path):
    db_file = tmp_path / "migrated.db"
    config = alembic_config_for(db_file)

    command.upgrade(config, "head")
    command.downgrade(config, "-1")
    assert not {"machines", "products", "inventory"} & table_names(db_file)

    command.upgrade(config, "head")
    assert {"machines", "products", "inventory"} <= table_names(db_file)
