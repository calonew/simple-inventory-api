from pydantic import BaseModel, ConfigDict, Field


class MachineCreate(BaseModel):
    name: str
    location: str


class MachineOut(MachineCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ProductCreate(BaseModel):
    name: str
    price: float = Field(gt=0)


class ProductOut(ProductCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class InventoryCreate(BaseModel):
    product_id: int
    quantity: int = Field(ge=0)


class InventoryUpdate(BaseModel):
    quantity: int = Field(ge=0)


class InventoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    machine_id: int
    product_id: int
    quantity: int
    product: ProductOut
