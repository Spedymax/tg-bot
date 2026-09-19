from aiogram.fsm.state import State, StatesGroup


class PetStates(StatesGroup):
    waiting_name = State()
    waiting_image = State()
