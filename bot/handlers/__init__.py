from . import (common, chat, system_prompt, providers, billing, projects, agent_cmds,
               terminal, github_cmds, agents_mode, memory, admin)

ALL_ROUTERS = [common.router, chat.commands_router, system_prompt.router, providers.router,
               billing.router, projects.router, agent_cmds.router, terminal.router,
               github_cmds.router, agents_mode.router, memory.router, admin.router,
               chat.free_text_router]

__all__ = ["ALL_ROUTERS"]
