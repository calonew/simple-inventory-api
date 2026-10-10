from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MachineCreate(BaseModel):
    name: RequiredText
    location: RequiredText


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
