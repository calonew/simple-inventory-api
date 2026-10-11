from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.database import get_db

LOW_STOCK_LIMIT = 5

app = FastAPI(title="Simple Inventory API")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


async def get_machine_or_404(db: AsyncSession, machine_id: int) -> models.Machine:
    machine = await db.get(models.Machine, machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


async def update_machine(
    db: AsyncSession, machine_id: int, data: schemas.MachineCreate
) -> models.Machine:
    machine = await get_machine_or_404(db, machine_id)
    machine.name = data.name
    machine.location = data.location
    await db.commit()
    await db.refresh(machine)
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


@app.put("/machines/{machine_id}", response_model=schemas.MachineOut)
async def put_machine(
    machine_id: int, data: schemas.MachineCreate, db: AsyncSession = Depends(get_db)
):
    return await update_machine(db, machine_id, data)


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

    item = models.Inventory(
        machine_id=machine_id, product_id=data.product_id, quantity=data.quantity
    )
    db.add(item)
    try:
        await db.commit()
    except IntegrityError:
        # the unique (machine_id, product_id) constraint is the real guard
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Product already exists in this machine"
        )
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


async def dashboard_context(db: AsyncSession) -> dict:
    result = await db.execute(
        select(models.Inventory, models.Machine)
        .join(models.Machine, models.Machine.id == models.Inventory.machine_id)
        .order_by(models.Machine.id, models.Inventory.product_id)
    )
    machines = await db.execute(select(models.Machine).order_by(models.Machine.id))
    return {
        "rows": result.all(),
        "machines": machines.scalars().all(),
        "low_stock_limit": LOW_STOCK_LIMIT,
    }


@app.get("/dashboard", include_in_schema=False)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    context = await dashboard_context(db)
    return templates.TemplateResponse(request, "dashboard.html", context)


@app.get("/dashboard/table", include_in_schema=False)
async def dashboard_table(request: Request, db: AsyncSession = Depends(get_db)):
    context = await dashboard_context(db)
    return templates.TemplateResponse(request, "inventory_table.html", context)


@app.get("/dashboard/machines/{machine_id}/edit", include_in_schema=False)
async def edit_machine_form(
    machine_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    machine = await get_machine_or_404(db, machine_id)
    context = {"machine": machine, "name": machine.name, "location": machine.location}
    return templates.TemplateResponse(request, "machine_form.html", context)


@app.get("/dashboard/edit-cancel", include_in_schema=False)
async def cancel_edit():
    return HTMLResponse("")


@app.post("/dashboard/machines/{machine_id}", include_in_schema=False)
async def save_machine_form(
    machine_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    # HTMX posts a url-encoded form; reading it by hand avoids python-multipart
    form = parse_qs((await request.body()).decode())
    name = form.get("name", [""])[0]
    location = form.get("location", [""])[0]

    try:
        data = schemas.MachineCreate(name=name, location=location)
    except ValidationError:
        machine = await get_machine_or_404(db, machine_id)
        context = {
            "machine": machine,
            "name": name,
            "location": location,
            "error": "Name and location are required.",
        }
        return templates.TemplateResponse(request, "machine_form.html", context)

    await update_machine(db, machine_id, data)
    context = await dashboard_context(db)
    return templates.TemplateResponse(request, "machine_saved.html", context)
