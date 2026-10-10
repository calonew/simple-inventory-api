from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import Base, engine, get_db

LOW_STOCK_LIMIT = 5

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Simple Inventory API")


def get_machine_or_404(db: Session, machine_id: int) -> models.Machine:
    machine = db.get(models.Machine, machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found")
    return machine


@app.get("/machines", response_model=list[schemas.MachineOut])
def list_machines(db: Session = Depends(get_db)):
    return db.query(models.Machine).all()


@app.post("/machines", response_model=schemas.MachineOut, status_code=201)
def create_machine(data: schemas.MachineCreate, db: Session = Depends(get_db)):
    machine = models.Machine(**data.model_dump())
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return machine


@app.get("/machines/{machine_id}", response_model=schemas.MachineOut)
def get_machine(machine_id: int, db: Session = Depends(get_db)):
    return get_machine_or_404(db, machine_id)


@app.get("/products", response_model=list[schemas.ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.query(models.Product).all()


@app.post("/products", response_model=schemas.ProductOut, status_code=201)
def create_product(data: schemas.ProductCreate, db: Session = Depends(get_db)):
    product = models.Product(**data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.get("/machines/{machine_id}/inventory", response_model=list[schemas.InventoryOut])
def list_inventory(machine_id: int, db: Session = Depends(get_db)):
    get_machine_or_404(db, machine_id)
    return db.query(models.Inventory).filter_by(machine_id=machine_id).all()


@app.post(
    "/machines/{machine_id}/inventory",
    response_model=schemas.InventoryOut,
    status_code=201,
)
def add_inventory(
    machine_id: int, data: schemas.InventoryCreate, db: Session = Depends(get_db)
):
    get_machine_or_404(db, machine_id)
    if db.get(models.Product, data.product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")

    existing = (
        db.query(models.Inventory)
        .filter_by(machine_id=machine_id, product_id=data.product_id)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="Product already exists in this machine"
        )

    item = models.Inventory(
        machine_id=machine_id, product_id=data.product_id, quantity=data.quantity
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.put(
    "/machines/{machine_id}/inventory/{product_id}",
    response_model=schemas.InventoryOut,
)
def update_inventory(
    machine_id: int,
    product_id: int,
    data: schemas.InventoryUpdate,
    db: Session = Depends(get_db),
):
    get_machine_or_404(db, machine_id)
    item = (
        db.query(models.Inventory)
        .filter_by(machine_id=machine_id, product_id=product_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    item.quantity = data.quantity
    db.commit()
    db.refresh(item)
    return item


@app.delete("/machines/{machine_id}/inventory/{product_id}", status_code=204)
def delete_inventory(machine_id: int, product_id: int, db: Session = Depends(get_db)):
    get_machine_or_404(db, machine_id)
    item = (
        db.query(models.Inventory)
        .filter_by(machine_id=machine_id, product_id=product_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    db.delete(item)
    db.commit()


@app.get("/low-stock", response_model=list[schemas.InventoryOut])
def low_stock(machine_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Inventory).filter(
        models.Inventory.quantity < LOW_STOCK_LIMIT
    )
    if machine_id is not None:
        query = query.filter_by(machine_id=machine_id)
    return query.all()
