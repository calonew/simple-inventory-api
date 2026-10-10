from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.database import Base, engine, get_db

LOW_STOCK_LIMIT = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Simple Inventory API", lifespan=lifespan)


async def get_machine_or_404(db: AsyncSession, machine_id: int) -> models.Machine:
    machine = await db.get(models.Machine, machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


async def get_inventory_item_or_404(
    db: AsyncSession, machine_id: int, product_id: int
) -> models.Inventory:
    await get_machine_or_404(db, machine_id)
    result = await db.execute(
        select(models.Inventory).filter_by(machine_id=machine_id, product_id=product_id)
    )
    item = result.scalars().first()
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return item


@app.get("/machines", response_model=list[schemas.MachineOut])
async def list_machines(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Machine))
    return result.scalars().all()


@app.post("/machines", response_model=schemas.MachineOut, status_code=201)
async def create_machine(data: schemas.MachineCreate, db: AsyncSession = Depends(get_db)):
    machine = models.Machine(**data.model_dump())
    db.add(machine)
    await db.commit()
    await db.refresh(machine)
    return machine


@app.get("/machines/{machine_id}", response_model=schemas.MachineOut)
async def get_machine(machine_id: int, db: AsyncSession = Depends(get_db)):
    return await get_machine_or_404(db, machine_id)


@app.get("/products", response_model=list[schemas.ProductOut])
async def list_products(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Product))
    return result.scalars().all()


@app.post("/products", response_model=schemas.ProductOut, status_code=201)
async def create_product(data: schemas.ProductCreate, db: AsyncSession = Depends(get_db)):
    product = models.Product(**data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@app.get("/machines/{machine_id}/inventory", response_model=list[schemas.InventoryOut])
async def list_inventory(machine_id: int, db: AsyncSession = Depends(get_db)):
    await get_machine_or_404(db, machine_id)
    result = await db.execute(
        select(models.Inventory).filter_by(machine_id=machine_id)
    )
    return result.scalars().all()


@app.post(
    "/machines/{machine_id}/inventory",
    response_model=schemas.InventoryOut,
    status_code=201,
)
async def add_inventory(
    machine_id: int, data: schemas.InventoryCreate, db: AsyncSession = Depends(get_db)
):
    await get_machine_or_404(db, machine_id)
    if await db.get(models.Product, data.product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")

    result = await db.execute(
        select(models.Inventory).filter_by(
            machine_id=machine_id, product_id=data.product_id
        )
    )
    if result.scalars().first() is not None:
        raise HTTPException(
            status_code=409, detail="Product already exists in this machine"
        )

    item = models.Inventory(
        machine_id=machine_id, product_id=data.product_id, quantity=data.quantity
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@app.put(
    "/machines/{machine_id}/inventory/{product_id}",
    response_model=schemas.InventoryOut,
)
async def update_inventory(
    machine_id: int,
    product_id: int,
    data: schemas.InventoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    item = await get_inventory_item_or_404(db, machine_id, product_id)
    item.quantity = data.quantity
    await db.commit()
    await db.refresh(item)
    return item


@app.delete("/machines/{machine_id}/inventory/{product_id}", status_code=204)
async def delete_inventory(
    machine_id: int, product_id: int, db: AsyncSession = Depends(get_db)
):
    item = await get_inventory_item_or_404(db, machine_id, product_id)
    await db.delete(item)
    await db.commit()


@app.get("/low-stock", response_model=list[schemas.InventoryOut])
async def low_stock(machine_id: int | None = None, db: AsyncSession = Depends(get_db)):
    query = select(models.Inventory).filter(models.Inventory.quantity < LOW_STOCK_LIMIT)
    if machine_id is not None:
        query = query.filter_by(machine_id=machine_id)
    result = await db.execute(query)
    return result.scalars().all()
