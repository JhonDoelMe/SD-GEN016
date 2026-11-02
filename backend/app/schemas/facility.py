import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class FacilityBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150, description="Назва об'єкту")
    address: Optional[str] = Field(None, max_length=255, description="Адреса / Локація")
    description: Optional[str] = Field(None, description="Опис або примітки")
    timezone: str = Field("Europe/Kyiv", max_length=50, description="Часовий пояс")
    yasno_enabled: bool = Field(False, description="Увімкнено моніторинг графіка YASNO")
    yasno_region_id: Optional[int] = Field(3, description="ID регіону YASNO (3 = Дніпропетровська обл)")
    yasno_dso_id: Optional[int] = Field(301, description="ID оператора ОСР (301 = ДТЕК ДнЕМ, 303 = ЦЕК)")
    yasno_group: Optional[str] = Field(None, max_length=10, description="Група / черга відключення (напр. 3.2)")


class FacilityCreate(FacilityBase):
    pass


class FacilityUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=150)
    address: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    timezone: Optional[str] = Field(None, max_length=50)
    yasno_enabled: Optional[bool] = None
    yasno_region_id: Optional[int] = None
    yasno_dso_id: Optional[int] = None
    yasno_group: Optional[str] = None


class FacilityOut(FacilityBase):
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    generator_count: int = 0
    fuel_stock_count: int = 0

    model_config = ConfigDict(from_attributes=True)
