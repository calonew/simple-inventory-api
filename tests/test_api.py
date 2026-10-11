import asyncio
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


def add_stock(client, machine_id, product_id, quantity):
    client.post(
        f"/machines/{machine_id}/inventory",
        json={"product_id": product_id, "quantity": quantity},
    )


def test_dashboard_returns_page(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_dashboard_shows_inventory(client):
    machine_id = create_machine(client, "Lobby", "Floor 1")
    cola = create_product(client, "Cola", 1.5)
    add_stock(client, machine_id, cola, 12)

    html = client.get("/dashboard").text

    assert "Lobby" in html
    assert "Floor 1" in html
    assert "Cola" in html
    assert "$1.50" in html
    assert "12" in html
    assert "OK" in html
    assert "Low Stock" not in html


def test_dashboard_marks_low_stock(client):
    machine_id = create_machine(client)
    cola = create_product(client, "Cola")
    chips = create_product(client, "Chips")
    add_stock(client, machine_id, cola, 3)
    add_stock(client, machine_id, chips, 5)

    html = client.get("/dashboard").text

    assert html.count("Low Stock") == 1
    assert html.count(">OK<") == 1


def test_dashboard_table_returns_only_the_table(client):
    machine_id = create_machine(client, "Lobby")
    cola = create_product(client, "Cola")
    add_stock(client, machine_id, cola, 2)

    response = client.get("/dashboard/table")

    assert response.status_code == 200
    assert "Cola" in response.text
    assert "<html" not in response.text


def test_update_machine(client):
    machine_id = create_machine(client, "Lobby", "Floor 1")

    response = client.put(
        f"/machines/{machine_id}", json={"name": "Cafeteria", "location": "Floor 2"}
    )

    assert response.status_code == 200
    assert response.json() == {"id": machine_id, "name": "Cafeteria", "location": "Floor 2"}
    assert client.get(f"/machines/{machine_id}").json()["name"] == "Cafeteria"


def test_update_machine_rejects_empty_name(client):
    machine_id = create_machine(client)

    response = client.put(f"/machines/{machine_id}", json={"name": "", "location": "Floor 2"})

    assert response.status_code == 422


def test_update_machine_rejects_empty_location(client):
    machine_id = create_machine(client)

    response = client.put(f"/machines/{machine_id}", json={"name": "Lobby", "location": "  "})

    assert response.status_code == 422


def test_update_missing_machine_returns_404(client):
    response = client.put("/machines/999", json={"name": "Lobby", "location": "Floor 1"})

    assert response.status_code == 404


def test_update_machine_keeps_inventory(client):
    machine_id = create_machine(client)
    cola = create_product(client, "Cola")
    add_stock(client, machine_id, cola, 7)

    client.put(f"/machines/{machine_id}", json={"name": "New name", "location": "New place"})

    items = client.get(f"/machines/{machine_id}/inventory").json()
    assert len(items) == 1
    assert items[0]["quantity"] == 7
    assert items[0]["product"]["name"] == "Cola"


def test_edit_form_shows_current_values(client):
    machine_id = create_machine(client, "Lobby", "Floor 1")

    response = client.get(f"/dashboard/machines/{machine_id}/edit")

    assert response.status_code == 200
    assert 'value="Lobby"' in response.text
    assert 'value="Floor 1"' in response.text


def test_edit_form_for_missing_machine_returns_404(client):
    assert client.get("/dashboard/machines/999/edit").status_code == 404


def test_dashboard_save_updates_machine(client):
    machine_id = create_machine(client, "Lobby", "Floor 1")
    cola = create_product(client, "Cola")
    add_stock(client, machine_id, cola, 7)

    response = client.post(
        f"/dashboard/machines/{machine_id}",
        data={"name": "Cafeteria", "location": "Floor 2"},
    )

    assert response.status_code == 200
    assert client.get(f"/machines/{machine_id}").json()["name"] == "Cafeteria"
    html = client.get("/dashboard").text
    assert "Cafeteria" in html
    assert "Floor 2" in html
    assert "Lobby" not in html
    assert "Cola" in html


def test_dashboard_save_with_empty_name_shows_error(client):
    machine_id = create_machine(client, "Lobby", "Floor 1")

    response = client.post(
        f"/dashboard/machines/{machine_id}", data={"name": "", "location": "Floor 2"}
    )

    assert response.status_code == 200
    assert "Name and location are required" in response.text
    assert client.get(f"/machines/{machine_id}").json()["name"] == "Lobby"


def test_cancel_edit_does_not_change_machine(client):
    machine_id = create_machine(client, "Lobby", "Floor 1")
    client.get(f"/dashboard/machines/{machine_id}/edit")

    response = client.get("/dashboard/edit-cancel")

    assert response.status_code == 200
    assert response.text.strip() == ""
    assert client.get(f"/machines/{machine_id}").json()["name"] == "Lobby"


def test_duplicate_added_by_another_request_returns_409(client, tmp_path):
    machine_id = create_machine(client)
    product_id = create_product(client)
    db_file = tmp_path / "test.db"

    # Simulates another request inserting the same row after our duplicate
    # check but before our commit.
    class RacingSession(AsyncSession):
        async def commit(self):
            with sqlite3.connect(db_file) as connection:
                connection.execute(
                    "INSERT INTO inventory (machine_id, product_id, quantity) "
                    "VALUES (?, ?, 1)",
                    (machine_id, product_id),
                )
            await super().commit()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    RacingSessionMaker = async_sessionmaker(
        engine, class_=RacingSession, expire_on_commit=False
    )

    async def racing_get_db():
        async with RacingSessionMaker() as db:
            yield db

    app.dependency_overrides[get_db] = racing_get_db
    racing_client = TestClient(app, raise_server_exceptions=False)

    response = racing_client.post(
        f"/machines/{machine_id}/inventory",
        json={"product_id": product_id, "quantity": 5},
    )

    assert response.status_code == 409
