"""Estados FSM para entradas multistep desde Telegram."""
from aiogram.fsm.state import State, StatesGroup


class SystemPromptStates(StatesGroup):
    waiting_text = State()
    waiting_import = State()


class ProjectStates(StatesGroup):
    waiting_name = State()
    waiting_rename = State()


class ProviderStates(StatesGroup):
    waiting_name = State()
    waiting_kind = State()
    waiting_url = State()


class RepoStates(StatesGroup):
    waiting_url = State()


class MemoryStates(StatesGroup):
    waiting_text = State()


class ConfigStates(StatesGroup):
    waiting_import = State()


class AgentsStates(StatesGroup):
    waiting_name = State()
    waiting_role = State()
    waiting_model = State()
    waiting_prompt = State()
