from aiogram.fsm.state import State, StatesGroup

class RegistrationStates(StatesGroup):
    waiting_name = State()
    waiting_how_found = State()
