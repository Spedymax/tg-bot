from aiogram.fsm.state import State, StatesGroup


class GameStates(StatesGroup):
    waiting_donation = State()
