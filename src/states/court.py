from aiogram.fsm.state import State, StatesGroup

class CourtStates(StatesGroup):
    # Group chat setup flow
    waiting_defendant = State()
    waiting_crime = State()
    # Gameplay — waiting for speech input in group chat
    waiting_speech = State()
    # Final word — collected via private DM
    waiting_final_word = State()
    # Private test mode (court_test command)
    private_waiting_defendant = State()
    private_waiting_crime = State()
