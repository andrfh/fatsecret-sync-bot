from enum import Enum

from pydantic import BaseModel, Field, model_validator


class MealStatus(str, Enum):
    ok = "ok"
    not_food = "not_food"
    too_complex = "too_complex"
    uncertain = "uncertain"


class MealKind(str, Enum):
    single_item = "single_item"
    composite_plate = "composite_plate"


# Names that must never survive as items: seasonings and non-visible additives.
# Matched against the normalized item name (lower-cased, stripped).
SEASONING_NAMES = {
    "salt",
    "sea salt",
    "table salt",
    "pepper",
    "black pepper",
    "white pepper",
    "ground pepper",
    "sugar",
    "oil",
    "cooking oil",
    "vegetable oil",
    "sunflower oil",
    "olive oil",
    "butter",
    "spice",
    "spices",
    "seasoning",
    "seasonings",
    "seasoning blend",
    "herb",
    "herbs",
    "dried herbs",
    "salt and pepper",
}


class MealItem(BaseModel):
    name: str = Field(min_length=1)
    brand: str | None = None
    amount_g: int = Field(ge=1)


class MealRecognition(BaseModel):
    status: MealStatus
    meal_kind: MealKind | None = None
    meal_name: str | None = None
    brand: str | None = None
    items: list[MealItem] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _normalize(self) -> "MealRecognition":
        if self.status is not MealStatus.ok:
            return self

        # 1. Drop seasonings / non-visible additives the model returned anyway.
        self.items = [
            item
            for item in self.items
            if item.name.strip().lower() not in SEASONING_NAMES
        ]

        if not (self.meal_name and self.meal_name.strip()):
            raise ValueError("status 'ok' requires a non-empty meal_name")
        if not self.items:
            raise ValueError("status 'ok' requires at least one visible food item")

        # 2. A single prepared food must be one item. Collapse an over-split
        #    result (burger -> bun + patty + cheese) into the whole food.
        if self.meal_kind is MealKind.single_item and len(self.items) > 1:
            self.items = [
                MealItem(
                    name=self.meal_name.strip(),
                    brand=self.brand,
                    amount_g=sum(item.amount_g for item in self.items),
                )
            ]

        return self

    def to_payload(self) -> dict:
        """Dict shape expected by the rest of the pipeline."""
        if self.status is not MealStatus.ok:
            return {"status": self.status.value}
        return self.model_dump(mode="json")
