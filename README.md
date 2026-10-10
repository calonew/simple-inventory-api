# Simple Inventory API

![Tests](https://github.com/calonew/simple-inventory-api/actions/workflows/tests.yml/badge.svg)

A small REST API for tracking the inventory of vending machines. It is a
learning/portfolio project that demonstrates the basics of FastAPI and
SQLAlchemy.

## What it does

- Manage vending machines (list, add, view)
- Manage products (list, add)
- Assign products to machines and track the quantity in each machine
- List products that are running low (quantity below 5), optionally for one machine

## Technologies

- Python 3.11+
- FastAPI
- SQLAlchemy (async) with SQLite
- Alembic for database migrations
- Pydantic
- pytest

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Database migrations

The database schema is managed with Alembic. Create or update the SQLite
database (`inventory.db`) before starting the API:

```bash
alembic upgrade head
```

To undo the most recent migration:

```bash
alembic downgrade -1
```

## Running the API

```bash
uvicorn app.main:app --reload
```

The app does not create tables by itself, so run the migration command above
first.

Interactive API documentation is available at http://127.0.0.1:8000/docs

## Running the tests

```bash
pytest
```

The tests create a temporary SQLite database with the Alembic migrations, so
your real data is not touched.

## Continuous integration

A GitHub Actions workflow (`.github/workflows/tests.yml`) runs the tests
automatically on every push and pull request, using Python 3.11 on Ubuntu.
If a test fails, the workflow fails.

## Development approach

New features are written test-first (red, green, refactor):

1. **Red:** write a test for the feature and see it fail.
2. **Green:** write the simplest code that makes the test pass.
3. **Refactor:** clean up the code while keeping all tests passing.

The delete-inventory endpoint was added this way.

## Example requests

```bash
# Create a machine
curl -X POST http://127.0.0.1:8000/machines \
  -H "Content-Type: application/json" \
  -d '{"name": "Lobby machine", "location": "Building A, floor 1"}'

# Create a product
curl -X POST http://127.0.0.1:8000/products \
  -H "Content-Type: application/json" \
  -d '{"name": "Cola", "price": 1.5}'

# Put 10 colas into machine 1
curl -X POST http://127.0.0.1:8000/machines/1/inventory \
  -H "Content-Type: application/json" \
  -d '{"product_id": 1, "quantity": 10}'

# Change the quantity
curl -X PUT http://127.0.0.1:8000/machines/1/inventory/1 \
  -H "Content-Type: application/json" \
  -d '{"quantity": 3}'

# List inventory of a machine
curl http://127.0.0.1:8000/machines/1/inventory

# Remove a product from a machine
curl -X DELETE http://127.0.0.1:8000/machines/1/inventory/1

# Low stock, for all machines or one machine
curl http://127.0.0.1:8000/low-stock
curl "http://127.0.0.1:8000/low-stock?machine_id=1"
```

## Endpoints

| Method | Path                                      | Description                    |
|--------|-------------------------------------------|--------------------------------|
| GET    | /machines                                 | List machines                  |
| POST   | /machines                                 | Add a machine                  |
| GET    | /machines/{id}                            | Machine details                |
| GET    | /products                                 | List products                  |
| POST   | /products                                 | Add a product                  |
| GET    | /machines/{id}/inventory                  | Inventory of a machine         |
| POST   | /machines/{id}/inventory                  | Add a product to a machine     |
| PUT    | /machines/{id}/inventory/{product_id}     | Update a quantity              |
| DELETE | /machines/{id}/inventory/{product_id}     | Remove a product from a machine|
| GET    | /low-stock                                | Items with quantity below 5    |
