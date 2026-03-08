from aiogram.fsm.state import State, StatesGroup

class ShopStates(StatesGroup):
    waiting_buy_quantity = State()
    waiting_sell_quantity = State()
