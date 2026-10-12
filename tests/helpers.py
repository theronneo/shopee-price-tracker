from shopee_tracker.domain import Product, ProductRef, Variant

VARIANT = Variant("3", "Black", 10000, True)
PRODUCT = Product(
    ProductRef("1", "2", "https://shopee.sg/product/1/2"),
    "Headphones",
    (VARIANT, Variant("4", "White", 11000, True)),
)


class CaptureMessenger:
    def __init__(self):
        self.messages = []

    async def send(self, text, keyboard=None):
        self.messages.append((text, keyboard))

    async def answer(self, query_id):
        pass


class StaticProvider:
    def __init__(self, product=PRODUCT):
        self.value = product

    async def product(self, ref):
        return self.value
