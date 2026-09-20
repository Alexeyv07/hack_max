from maxapi.context.state_machine import State, StatesGroup


class ChatLinkStates(StatesGroup):
    choosing = State()
    postal = State()
